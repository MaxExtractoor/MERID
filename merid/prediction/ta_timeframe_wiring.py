"""
TA Timeframe Wiring for Kalshi 15-Minute Markets

This module wires technical analysis timeframes for the 15-minute Kalshi crypto
trading system, ensuring:
- 1-5 minute candles are used for primary entry signals
- 15-minute candles are used for trend confirmation
- Timeframe alignment across momentum, FVG, and candlestick pattern modules
- Per-asset timeframe tuning for BTC/ETH/SOL/XRP/DOGE

Key Invariants:
1. Primary timeframe (1-5m) drives entry signal generation
2. Confirmation timeframe (15m) validates trend direction
3. Timeframe data is aligned to market resolution windows
4. Per-asset volatility tuning applied to timeframe selection

Usage::

    from merid.prediction.ta_timeframe_wiring import (
        TimeframeConfig,
        get_timeframe_config,
        validate_timeframe_alignment,
        TimeframeWiring
    )
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timezone, timedelta
from utils.logger import get_logger

logger = get_logger("ta_timeframe_wiring")


class TimeframeType(str, Enum):
    """Timeframe classification."""
    PRIMARY = "primary"  # Entry signal generation (1-5m)
    CONFIRMATION = "confirmation"  # Trend validation (15m)
    CONTEXT = "context"  # Higher-level context (1h, 4h, daily)


class CandleResolution(str, Enum):
    """Candle resolution in minutes."""
    ONE_MINUTE = "1m"
    FIVE_MINUTE = "5m"
    FIFTEEN_MINUTE = "15m"
    ONE_HOUR = "1h"
    FOUR_HOUR = "4h"
    DAILY = "1d"
    
    @property
    def minutes(self) -> int:
        """Convert to minutes."""
        mapping = {
            CandleResolution.ONE_MINUTE: 1,
            CandleResolution.FIVE_MINUTE: 5,
            CandleResolution.FIFTEEN_MINUTE: 15,
            CandleResolution.ONE_HOUR: 60,
            CandleResolution.FOUR_HOUR: 240,
            CandleResolution.DAILY: 1440,
        }
        return mapping[self]


@dataclass
class TimeframeConfig:
    """Timeframe configuration for an asset."""
    
    asset: str
    primary_resolution: CandleResolution  # Entry signals (1-5m)
    confirmation_resolution: CandleResolution  # Trend validation (15m)
    context_resolutions: List[CandleResolution] = field(default_factory=list)
    
    # Per-asset tuning parameters
    volatility_multiplier: float = 1.0  # Adjust timeframe based on volatility
    min_velocity_threshold: float = 0.0001  # Minimum velocity for signal
    max_velocity_threshold: float = 0.001  # Maximum velocity for signal
    
    # Candlestick pattern parameters
    min_pattern_strength: float = 0.7  # Minimum pattern confidence
    volume_multiplier: float = 1.5  # Volume threshold for pattern validity
    
    def to_dict(self) -> Dict:
        return {
            "asset": self.asset,
            "primary_resolution": self.primary_resolution.value,
            "confirmation_resolution": self.confirmation_resolution.value,
            "context_resolutions": [r.value for r in self.context_resolutions],
            "volatility_multiplier": self.volatility_multiplier,
            "min_velocity_threshold": self.min_velocity_threshold,
            "max_velocity_threshold": self.max_velocity_threshold,
            "min_pattern_strength": self.min_pattern_strength,
            "volume_multiplier": self.volume_multiplier,
        }


# Default timeframe configurations per asset
# CRITICAL: These are the canonical configurations for 15m Kalshi trading
_DEFAULT_TIMEFRAME_CONFIGS: Dict[str, TimeframeConfig] = {
    "BTC": TimeframeConfig(
        asset="BTC",
        primary_resolution=CandleResolution.ONE_MINUTE,  # BTC: 1m for entry
        confirmation_resolution=CandleResolution.FIFTEEN_MINUTE,
        context_resolutions=[CandleResolution.ONE_HOUR, CandleResolution.FOUR_HOUR],
        volatility_multiplier=1.0,
        min_velocity_threshold=0.00005,  # BTC: lower threshold (slower moving)
        max_velocity_threshold=0.0008,
        min_pattern_strength=0.75,
        volume_multiplier=1.5,
    ),
    "ETH": TimeframeConfig(
        asset="ETH",
        primary_resolution=CandleResolution.ONE_MINUTE,  # ETH: 1m for entry
        confirmation_resolution=CandleResolution.FIFTEEN_MINUTE,
        context_resolutions=[CandleResolution.ONE_HOUR, CandleResolution.FOUR_HOUR],
        volatility_multiplier=1.2,  # ETH: more volatile
        min_velocity_threshold=0.00008,
        max_velocity_threshold=0.0010,
        min_pattern_strength=0.70,
        volume_multiplier=1.4,
    ),
    "SOL": TimeframeConfig(
        asset="SOL",
        primary_resolution=CandleResolution.FIVE_MINUTE,  # SOL: 5m for entry (higher vol)
        confirmation_resolution=CandleResolution.FIFTEEN_MINUTE,
        context_resolutions=[CandleResolution.ONE_HOUR],
        volatility_multiplier=1.5,  # SOL: highly volatile
        min_velocity_threshold=0.00015,
        max_velocity_threshold=0.0015,
        min_pattern_strength=0.65,
        volume_multiplier=1.3,
    ),
    "XRP": TimeframeConfig(
        asset="XRP",
        primary_resolution=CandleResolution.FIVE_MINUTE,  # XRP: 5m for entry
        confirmation_resolution=CandleResolution.FIFTEEN_MINUTE,
        context_resolutions=[CandleResolution.ONE_HOUR],
        volatility_multiplier=1.3,
        min_velocity_threshold=0.00012,
        max_velocity_threshold=0.0012,
        min_pattern_strength=0.68,
        volume_multiplier=1.35,
    ),
    "DOGE": TimeframeConfig(
        asset="DOGE",
        primary_resolution=CandleResolution.FIVE_MINUTE,  # DOGE: 5m for entry (very high vol)
        confirmation_resolution=CandleResolution.FIFTEEN_MINUTE,
        context_resolutions=[CandleResolution.ONE_HOUR],
        volatility_multiplier=1.8,  # DOGE: extremely volatile
        min_velocity_threshold=0.00020,
        max_velocity_threshold=0.0020,
        min_pattern_strength=0.60,
        volume_multiplier=1.2,
    ),
}


def get_timeframe_config(asset: str) -> Optional[TimeframeConfig]:
    """Get timeframe configuration for an asset.
    
    Args:
        asset: Asset symbol (BTC, ETH, SOL, XRP, DOGE)
        
    Returns:
        TimeframeConfig or None if asset not supported
    """
    return _DEFAULT_TIMEFRAME_CONFIGS.get(asset.upper())


def validate_timeframe_alignment(
    primary_resolution: CandleResolution,
    confirmation_resolution: CandleResolution,
    market_window_minutes: int = 15,
) -> Tuple[bool, Optional[str]]:
    """Validate that timeframes are aligned to market window.
    
    Invariant:
    - Primary resolution must be <= market window (1-5m for 15m window)
    - Confirmation resolution must equal market window (15m for 15m window)
    - Primary resolution must divide evenly into confirmation resolution
    
    Args:
        primary_resolution: Primary timeframe resolution
        confirmation_resolution: Confirmation timeframe resolution
        market_window_minutes: Market window in minutes (default 15)
        
    Returns:
        (is_valid, error_message)
    """
    primary_minutes = primary_resolution.minutes
    confirmation_minutes = confirmation_resolution.minutes
    
    # Check primary <= market window
    if primary_minutes > market_window_minutes:
        return False, (
            f"Primary resolution {primary_resolution.value} ({primary_minutes}m) "
            f"exceeds market window {market_window_minutes}m"
        )
    
    # Check confirmation == market window
    if confirmation_minutes != market_window_minutes:
        return False, (
            f"Confirmation resolution {confirmation_resolution.value} ({confirmation_minutes}m) "
            f"must equal market window {market_window_minutes}m"
        )
    
    # Check primary divides into confirmation
    if confirmation_minutes % primary_minutes != 0:
        return False, (
            f"Primary resolution {primary_resolution.value} ({primary_minutes}m) "
            f"must divide evenly into confirmation {confirmation_resolution.value} ({confirmation_minutes}m)"
        )
    
    return True, None


@dataclass
class TimeframeData:
    """Candle data for a specific timeframe."""
    
    resolution: CandleResolution
    open: float
    high: float
    low: float
    close: float
    volume: float
    timestamp: datetime
    
    def to_dict(self) -> Dict:
        return {
            "resolution": self.resolution.value,
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "volume": self.volume,
            "timestamp": self.timestamp.isoformat(),
        }


class TimeframeWiring:
    """Wires TA timeframes for signal generation."""
    
    def __init__(self):
        self._configs: Dict[str, TimeframeConfig] = _DEFAULT_TIMEFRAME_CONFIGS.copy()
        self._data_cache: Dict[str, Dict[str, List[TimeframeData]]] = {}
    
    def get_config(self, asset: str) -> Optional[TimeframeConfig]:
        """Get timeframe config for asset."""
        return self._configs.get(asset.upper())
    
    def add_candle_data(
        self,
        asset: str,
        resolution: CandleResolution,
        candle: TimeframeData,
    ) -> None:
        """Add candle data to cache."""
        asset_upper = asset.upper()
        if asset_upper not in self._data_cache:
            self._data_cache[asset_upper] = {}
        
        res_key = resolution.value
        if res_key not in self._data_cache[asset_upper]:
            self._data_cache[asset_upper][res_key] = []
        
        self._data_cache[asset_upper][res_key].append(candle)
        
        # Keep only last 100 candles per resolution
        if len(self._data_cache[asset_upper][res_key]) > 100:
            self._data_cache[asset_upper][res_key] = self._data_cache[asset_upper][res_key][-100:]
    
    def get_primary_candles(
        self,
        asset: str,
        count: int = 10,
    ) -> List[TimeframeData]:
        """Get primary timeframe candles for entry signals.
        
        Args:
            asset: Asset symbol
            count: Number of candles to return
            
        Returns:
            List of primary timeframe candles
        """
        config = self.get_config(asset)
        if config is None:
            return []
        
        asset_upper = asset.upper()
        if asset_upper not in self._data_cache:
            return []
        
        res_key = config.primary_resolution.value
        candles = self._data_cache[asset_upper].get(res_key, [])
        
        return candles[-count:] if candles else []
    
    def get_confirmation_candles(
        self,
        asset: str,
        count: int = 5,
    ) -> List[TimeframeData]:
        """Get confirmation timeframe candles for trend validation.
        
        Args:
            asset: Asset symbol
            count: Number of candles to return
            
        Returns:
            List of confirmation timeframe candles
        """
        config = self.get_config(asset)
        if config is None:
            return []
        
        asset_upper = asset.upper()
        if asset_upper not in self._data_cache:
            return []
        
        res_key = config.confirmation_resolution.value
        candles = self._data_cache[asset_upper].get(res_key, [])
        
        return candles[-count:] if candles else []
    
    def validate_timeframe_consistency(self, asset: str) -> Tuple[bool, Optional[str]]:
        """Validate that timeframe data is consistent.
        
        Invariant:
        - Primary candles must be available
        - Confirmation candles must be available
        - Timeframes must be aligned to market window
        
        Args:
            asset: Asset symbol
            
        Returns:
            (is_valid, error_message)
        """
        config = self.get_config(asset)
        if config is None:
            return False, f"No timeframe config for asset {asset}"
        
        # Validate alignment
        is_aligned, error = validate_timeframe_alignment(
            config.primary_resolution,
            config.confirmation_resolution,
            market_window_minutes=15,
        )
        if not is_aligned:
            return False, error
        
        # Check data availability
        primary_candles = self.get_primary_candles(asset, count=1)
        if not primary_candles:
            return False, f"No primary candles available for {asset}"
        
        confirmation_candles = self.get_confirmation_candles(asset, count=1)
        if not confirmation_candles:
            return False, f"No confirmation candles available for {asset}"
        
        return True, None


# Singleton instance
_timeframe_wiring: Optional[TimeframeWiring] = None


def get_timeframe_wiring() -> TimeframeWiring:
    """Get the global timeframe wiring singleton."""
    global _timeframe_wiring
    if _timeframe_wiring is None:
        _timeframe_wiring = TimeframeWiring()
    return _timeframe_wiring


# Invariant documentation
TIMEFRAME_INVARIANTS = """
TA Timeframe Invariants for Kalshi 15-Minute Markets (2026-07-23)

1. Primary Timeframe (Entry Signals):
   - BTC, ETH: 1-minute candles for entry signal generation
   - SOL, XRP, DOGE: 5-minute candles for entry (higher volatility)
   - Primary resolution must be <= market window (15m)
   - Primary resolution must divide evenly into confirmation resolution

2. Confirmation Timeframe (Trend Validation):
   - All assets: 15-minute candles for trend confirmation
   - Confirmation resolution must equal market window (15m)
   - Used to validate primary signal direction

3. Context Timeframes (Higher-Level Context):
   - BTC, ETH: 1h, 4h for regime detection
   - SOL, XRP, DOGE: 1h for regime detection
   - Not used for entry signals, only for context

4. Per-Asset Volatility Tuning:
   - BTC: volatility_multiplier=1.0, min_velocity=0.00005
   - ETH: volatility_multiplier=1.2, min_velocity=0.00008
   - SOL: volatility_multiplier=1.5, min_velocity=0.00015
   - XRP: volatility_multiplier=1.3, min_velocity=0.00012
   - DOGE: volatility_multiplier=1.8, min_velocity=0.00020

5. Candlestick Pattern Parameters:
   - Pattern strength threshold: 0.60-0.75 per asset
   - Volume multiplier: 1.2-1.5 per asset
   - Patterns only valid if volume exceeds threshold

6. Timeframe Alignment:
   - 1m divides into 15m (15 candles per confirmation)
   - 5m divides into 15m (3 candles per confirmation)
   - Alignment ensures consistent signal timing

7. Data Availability:
   - Primary candles must be available for signal generation
   - Confirmation candles must be available for trend validation
   - Missing data blocks signal generation (fail-safe)
"""
