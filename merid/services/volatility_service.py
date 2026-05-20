"""Volatility Service — Centralized volatility calculation with caching.

This module provides a unified source of volatility estimates for all
subsystems (CT, Grid, RiskEngine), eliminating divergence in vol calculations.

Usage::
    from merid.services.volatility_service import VolatilityService, get_volatility_service
    
    # Get singleton instance
    service = get_volatility_service()
    
    # Get volatility estimate
    estimate = await service.get_volatility("BTC", "15m")
    
    print(f"Realized vol: {estimate.realized_vol_annual:.1%}")
    print(f"ATR-14: {estimate.atr_14:.2f}")
"""

from __future__ import annotations

import asyncio
import threading
import numpy as np
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional, List, Any
from collections import deque

from utils.logger import get_logger

logger = get_logger("merid.services.volatility_service")


@dataclass
class VolatilityEstimate:
    """Volatility estimate for an asset/timeframe.
    
    All volatility values are expressed as decimals (0.20 = 20%).
    ATR values are in price units (cents or dollars depending on context).
    """
    asset: str
    """Asset symbol (e.g., "BTC", "ETH")."""
    
    timeframe: str
    """Timeframe (e.g., "15m", "1h", "daily")."""
    
    realized_vol_annual: float
    """Annualized realized volatility (decimal)."""
    
    realized_vol_24h: float
    """24-hour realized volatility (decimal)."""
    
    atr_14: float
    """14-period Average True Range."""
    
    confidence: float
    """Confidence score (0-1) based on data quality."""
    
    timestamp: datetime
    """When this estimate was computed."""
    
    data_points: int
    """Number of data points used in calculation."""
    
    price_latest: Optional[float] = None
    """Latest price at time of calculation."""
    
    def is_fresh(self, max_age_seconds: float = 60.0) -> bool:
        """Check if estimate is fresh enough to use."""
        age = (datetime.now(timezone.utc) - self.timestamp).total_seconds()
        return age < max_age_seconds
    
    def is_high_vol(self, threshold: float = 0.50) -> bool:
        """Check if in high volatility regime."""
        return self.realized_vol_annual > threshold


@dataclass
class CandleData:
    """Internal candle data structure."""
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float


class VolatilityService:
    """Centralized volatility calculation with caching.
    
    This service provides unified volatility estimates for all MERID
    subsystems, ensuring consistent risk calculations across CT, Grid,
    and RiskEngine.
    
    Features:
    - Per-asset/timeframe volatility caching
    - ATR and realized volatility calculation
    - Configurable lookback periods
    - Thread-safe operations
    """
    
    _instance: Optional[VolatilityService] = None
    _instance_lock = threading.Lock()
    
    # Default cache TTL
    DEFAULT_CACHE_TTL_SECONDS = 60.0
    
    # Maximum candles to retain per series
    MAX_CANDLE_HISTORY = 200
    
    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
    
    def __init__(
        self,
        cache_ttl_seconds: float = DEFAULT_CACHE_TTL_SECONDS,
        default_lookback: int = 30
    ):
        if self._initialized:
            return
            
        self._cache_ttl = timedelta(seconds=cache_ttl_seconds)
        self._default_lookback = default_lookback
        
        # Cache: (asset, timeframe) -> (timestamp, estimate)
        self._cache: Dict[tuple, tuple] = {}
        self._cache_lock = asyncio.Lock()
        
        # Candle history: (asset, timeframe) -> deque[CandleData]
        self._candles: Dict[tuple, deque] = {}
        self._candles_lock = asyncio.Lock()
        
        # Fetch function overrides (for testing)
        self._fetch_functions: Dict[str, callable] = {}
        
        self._initialized = True
        logger.info(f"VolatilityService initialized (TTL={cache_ttl_seconds}s)")
    
    async def get_volatility(
        self,
        asset: str,
        timeframe: str = "15m",
        min_data_points: int = 14,
        force_refresh: bool = False
    ) -> Optional[VolatilityEstimate]:
        """Get volatility estimate, computing if cache miss or stale.
        
        Args:
            asset: Asset symbol (e.g., "BTC", "ETH")
            timeframe: Timeframe ("15m", "1h", "daily", etc.)
            min_data_points: Minimum candles required for calculation
            force_refresh: Ignore cache and force recalculation
            
        Returns:
            VolatilityEstimate or None if insufficient data
        """
        cache_key = (asset.upper(), timeframe.lower())
        
        # Check cache
        if not force_refresh:
            async with self._cache_lock:
                cached = self._cache.get(cache_key)
                if cached:
                    timestamp, estimate = cached
                    if datetime.now(timezone.utc) - timestamp < self._cache_ttl:
                        logger.debug(f"Volatility cache hit for {asset}:{timeframe}")
                        return estimate
        
        # Compute fresh estimate
        estimate = await self._compute_volatility(
            asset, timeframe, min_data_points
        )
        
        if estimate:
            # Update cache
            async with self._cache_lock:
                self._cache[cache_key] = (datetime.now(timezone.utc), estimate)
        
        return estimate
    
    async def _compute_volatility(
        self,
        asset: str,
        timeframe: str,
        min_data_points: int
    ) -> Optional[VolatilityEstimate]:
        """Compute volatility from market data.
        
        Args:
            asset: Asset symbol
            timeframe: Timeframe
            min_data_points: Minimum required candles
            
        Returns:
            VolatilityEstimate or None
        """
        # Fetch candles
        candles = await self._fetch_candles(asset, timeframe)
        
        if len(candles) < min_data_points:
            logger.warning(
                f"Insufficient data for {asset}:{timeframe}: "
                f"{len(candles)} < {min_data_points}"
            )
            return None
        
        try:
            # Extract close prices
            closes = np.array([c.close for c in candles])
            
            # Calculate log returns
            log_returns = np.diff(np.log(closes))
            
            # Realized volatility (annualized)
            periods_per_year = self._periods_per_year(timeframe)
            realized_vol = np.std(log_returns) * np.sqrt(periods_per_year)
            
            # 24h volatility
            periods_24h = self._periods_per_24h(timeframe)
            if len(log_returns) >= periods_24h:
                vol_24h = np.std(log_returns[-periods_24h:]) * np.sqrt(periods_per_year)
            else:
                vol_24h = realized_vol
            
            # ATR(14)
            highs = np.array([c.high for c in candles[-14:]])
            lows = np.array([c.low for c in candles[-14:]])
            atr = np.mean(highs - lows) if len(highs) > 0 else 0.0
            
            # Confidence based on data quality
            confidence = min(1.0, len(candles) / (min_data_points * 2))
            
            return VolatilityEstimate(
                asset=asset,
                timeframe=timeframe,
                realized_vol_annual=float(realized_vol),
                realized_vol_24h=float(vol_24h),
                atr_14=float(atr),
                confidence=confidence,
                timestamp=datetime.now(timezone.utc),
                data_points=len(candles),
                price_latest=closes[-1] if len(closes) > 0 else None
            )
            
        except Exception as e:
            logger.error(f"Error computing volatility for {asset}:{timeframe}: {e}")
            return None
    
    async def _fetch_candles(
        self,
        asset: str,
        timeframe: str
    ) -> List[CandleData]:
        """Fetch candles for volatility calculation.
        
        Tries multiple sources in order:
        1. Internal candle history
        2. Kalshi market state
        3. Registered fetch function
        
        Args:
            asset: Asset symbol
            timeframe: Timeframe
            
        Returns:
            List of CandleData
        """
        cache_key = (asset.upper(), timeframe.lower())
        
        # Check internal history
        async with self._candles_lock:
            if cache_key in self._candles:
                return list(self._candles[cache_key])
        
        # Try to fetch from Kalshi market state
        try:
            candles = await self._fetch_from_kalshi_state(asset, timeframe)
            if candles:
                return candles
        except Exception as e:
            logger.debug(f"Kalshi state fetch failed: {e}")
        
        # Try registered fetch function
        fetch_fn = self._fetch_functions.get(timeframe.lower())
        if fetch_fn:
            try:
                data = await fetch_fn(asset, timeframe)
                if data:
                    return self._normalize_candles(data)
            except Exception as e:
                logger.warning(f"Registered fetch failed: {e}")
        
        return []
    
    async def _fetch_from_kalshi_state(
        self,
        asset: str,
        timeframe: str
    ) -> Optional[List[CandleData]]:
        """Fetch candles from Kalshi market state.
        
        Args:
            asset: Asset symbol
            timeframe: Timeframe
            
        Returns:
            List of CandleData or None
        """
        try:
            from merid.event_venues.kalshi.market_state import get_kalshi_market_state_store
            
            store = get_kalshi_market_state_store()
            
            # Map asset to series ticker
            series_ticker = self._asset_to_series_ticker(asset, timeframe)
            
            # Get unified market state
            unified = store.get_unified(series_ticker)
            
            if not unified or not unified.candles:
                return None
            
            # Convert to CandleData
            candles = []
            for c in unified.candles[-100:]:  # Last 100 candles
                candles.append(CandleData(
                    timestamp=datetime.fromtimestamp(c.ts),
                    open=c.open_cents / 100.0,
                    high=c.high_cents / 100.0,
                    low=c.low_cents / 100.0,
                    close=c.close_cents / 100.0,
                    volume=c.volume
                ))
            
            return candles
            
        except Exception as e:
            logger.debug(f"Failed to fetch from Kalshi state: {e}")
            return None
    
    def _asset_to_series_ticker(self, asset: str, timeframe: str) -> str:
        """Convert asset/timeframe to series ticker."""
        # Map to Kalshi series convention
        asset_map = {
            "BTC": "KXBTC",
            "ETH": "KXETH",
            "SOL": "KXSOL",
            "XRP": "KXXRP",
            "DOGE": "KXDOGE",
        }
        
        suffix_map = {
            "15m": "-15M",
            "1h": "",
            "hourly": "",
            "daily": "-D",
            "weekly": "-W",
        }
        
        base = asset_map.get(asset.upper(), f"KX{asset.upper()}")
        suffix = suffix_map.get(timeframe.lower(), "")
        
        return f"{base}{suffix}"
    
    def _normalize_candles(self, data: Any) -> List[CandleData]:
        """Normalize various candle formats to CandleData."""
        candles = []
        
        for item in data:
            if isinstance(item, dict):
                candles.append(CandleData(
                    timestamp=datetime.fromtimestamp(item.get("ts", 0)),
                    open=float(item.get("open", 0)),
                    high=float(item.get("high", 0)),
                    low=float(item.get("low", 0)),
                    close=float(item.get("close", 0)),
                    volume=float(item.get("volume", 0))
                ))
        
        return candles
    
    def _periods_per_year(self, timeframe: str) -> int:
        """Calculate periods per year for annualization."""
        mapping = {
            "1m": 525600,
            "5m": 105120,
            "15m": 35040,
            "30m": 17520,
            "1h": 8760,
            "4h": 2190,
            "daily": 365,
            "weekly": 52,
        }
        return mapping.get(timeframe.lower(), 35040)  # Default to 15m
    
    def _periods_per_24h(self, timeframe: str) -> int:
        """Calculate periods per 24 hours."""
        mapping = {
            "1m": 1440,
            "5m": 288,
            "15m": 96,
            "30m": 48,
            "1h": 24,
            "4h": 6,
            "daily": 1,
        }
        return mapping.get(timeframe.lower(), 96)  # Default to 15m
    
    async def ingest_candle(
        self,
        asset: str,
        timeframe: str,
        timestamp: datetime,
        open_price: float,
        high: float,
        low: float,
        close: float,
        volume: float
    ) -> None:
        """Ingest a new candle into the service.
        
        This allows external systems to feed candle data directly.
        
        Args:
            asset: Asset symbol
            timeframe: Timeframe
            timestamp: Candle timestamp
            open_price: Open price
            high: High price
            low: Low price
            close: Close price
            volume: Volume
        """
        cache_key = (asset.upper(), timeframe.lower())
        
        async with self._candles_lock:
            if cache_key not in self._candles:
                self._candles[cache_key] = deque(maxlen=self.MAX_CANDLE_HISTORY)
            
            self._candles[cache_key].append(CandleData(
                timestamp=timestamp,
                open=open_price,
                high=high,
                low=low,
                close=close,
                volume=volume
            ))
        
        # Invalidate cache for this series
        async with self._cache_lock:
            if cache_key in self._cache:
                del self._cache[cache_key]
    
    def register_fetch_function(
        self,
        timeframe: str,
        fetch_fn: callable
    ) -> None:
        """Register a custom fetch function for a timeframe.
        
        Args:
            timeframe: Timeframe to register for
            fetch_fn: Async function(asset, timeframe) -> candle data
        """
        self._fetch_functions[timeframe.lower()] = fetch_fn
    
    async def clear_cache(self) -> None:
        """Clear the volatility cache."""
        async with self._cache_lock:
            self._cache.clear()
        logger.info("Volatility cache cleared")
    
    def get_cache_stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        return {
            "cached_series": len(self._cache),
            "candle_series": len(self._candles),
            "registered_fetchers": list(self._fetch_functions.keys()),
        }


# ═══════════════════════════════════════════════════════════════════════════════
# Singleton accessor
# ═══════════════════════════════════════════════════════════════════════════════

_volatility_service_instance: Optional[VolatilityService] = None


def get_volatility_service() -> VolatilityService:
    """Get the global VolatilityService instance."""
    global _volatility_service_instance
    
    if _volatility_service_instance is None:
        _volatility_service_instance = VolatilityService()
    
    return _volatility_service_instance


def reset_volatility_service() -> None:
    """Reset the global instance (for testing)."""
    global _volatility_service_instance
    _volatility_service_instance = None
