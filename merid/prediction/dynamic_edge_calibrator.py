"""Dynamic Edge Calibrator — Computes edge thresholds from market conditions.

Replaces static YAML edge values with dynamic calculations based on:
- Realized volatility (trailing 24h, 7d)
- Market liquidity (spread, depth, volume)
- Asset-specific risk adjustments
- Timeframe scaling factors

Usage::

    from merid.prediction.dynamic_edge_calibrator import get_dynamic_edge_calibrator
    
    calibrator = get_dynamic_edge_calibrator()
    edge_threshold = calibrator.get_edge_threshold("BTC", "15m")
    # Returns dynamically computed edge based on current market conditions
"""

from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass, field
from decimal import Decimal, ROUND_HALF_UP
from typing import Dict, List, Optional, Tuple
from collections import deque

from utils.logger import get_logger

logger = get_logger("merid.prediction.dynamic_edge_calibrator")


@dataclass(frozen=True)
class AssetVolatilityState:
    """Volatility metrics for an asset."""
    asset: str
    rv_24h: float  # Realized volatility (24h)
    rv_7d: float   # Realized volatility (7d)
    spread_bps: float  # Average spread in basis points
    volume_24h: float  # 24h volume in USD
    last_update: float


@dataclass
class DynamicEdgeConfig:
    """Configuration for dynamic edge calculation."""
    # Base edge for most liquid asset (BTC) at lowest volatility
    base_edge: Decimal = Decimal("0.008")
    
    # Volatility scaling: edge increases with sqrt(vol)
    vol_scaling_factor: Decimal = Decimal("0.5")
    
    # Asset risk multipliers (relative to BTC)
    asset_risk_multipliers: Dict[str, Decimal] = field(default_factory=lambda: {
        "BTC": Decimal("1.0"),
        "ETH": Decimal("1.15"),
        "SOL": Decimal("1.35"),
        "XRP": Decimal("1.45"),
        "DOGE": Decimal("1.60"),
    })
    
    # Timeframe scaling factors (longer = higher edge requirement)
    timeframe_multipliers: Dict[str, Decimal] = field(default_factory=lambda: {
        "15m": Decimal("1.0"),
        "1h": Decimal("1.15"),
        "daily": Decimal("1.35"),
        "weekly": Decimal("1.60"),
        "monthly": Decimal("1.80"),
        "annual": Decimal("2.0"),
    })
    
    # Minimum edge floor (absolute minimum regardless of conditions)
    min_edge_floor: Decimal = Decimal("0.005")
    
    # Maximum edge ceiling (prevent excessive thresholds)
    max_edge_ceiling: Decimal = Decimal("0.08")
    
    # Volatility lookback windows in hours
    vol_lookback_short: int = 24
    vol_lookback_long: int = 168  # 7 days
    
    # Spread impact: higher spread = higher edge requirement
    spread_scaling: Decimal = Decimal("0.1")  # per 10 bps


class DynamicEdgeCalibrator:
    """Computes dynamic edge thresholds based on market conditions.
    
    This replaces the hardcoded edge values in crypto_threshold_matrix.yaml
    with dynamically computed values that respond to:
    - Market volatility
    - Liquidity conditions  
    - Asset characteristics
    - Timeframe risk scaling
    """
    
    def __init__(self, config: Optional[DynamicEdgeConfig] = None):
        self.config = config or DynamicEdgeConfig()
        self._volatility_cache: Dict[str, AssetVolatilityState] = {}
        # TEMPORARILY DISABLED: threading.Lock causing deadlock during startup
        # TODO: Re-enable lock after startup is stable and investigate proper async synchronization
        # self._cache_lock = threading.Lock()
        self._cache_lock = None  # Disabled to prevent startup hang
        self._last_update = 0.0
        self._cache_ttl_seconds = 300  # 5 minute TTL
        
    def _get_cached_volatility(self, asset: str) -> Optional[AssetVolatilityState]:
        """Get cached volatility data if fresh."""
        if self._cache_lock is not None:
            with self._cache_lock:
                state = self._volatility_cache.get(asset)
                if state is None:
                    return None
                if time.time() - state.last_update > self._cache_ttl_seconds:
                    return None
                return state
        else:
            # Lock disabled - direct access (startup workaround)
            state = self._volatility_cache.get(asset)
            if state is None:
                return None
            if time.time() - state.last_update > self._cache_ttl_seconds:
                return None
            return state
    
    def _fetch_volatility_data(self, asset: str) -> AssetVolatilityState:
        """Fetch current volatility data for an asset.
        
        In production, this fetches from price feed/volatility tracker.
        Falls back to sensible defaults if data unavailable.
        """
        try:
            # Try to get from crypto vol band indicator stack
            from merid.prediction.crypto_vol_indicators import get_crypto_vol_indicator_stack
            stack = get_crypto_vol_indicator_stack()
            vol_data = stack.get_latest_volatility(asset)
            
            if vol_data:
                return AssetVolatilityState(
                    asset=asset,
                    rv_24h=vol_data.get("rv_24h", 0.50),
                    rv_7d=vol_data.get("rv_7d", 0.55),
                    spread_bps=vol_data.get("spread_bps", 10.0),
                    volume_24h=vol_data.get("volume_24h", 1_000_000_000),
                    last_update=time.time(),
                )
        except Exception as e:
            logger.debug(f"Could not fetch volatility for {asset}: {e}")
        
        # Fallback: return default volatility estimates by asset
        default_vols = {
            "BTC": (0.45, 0.50, 8.0),   # 45% 24h vol, 50% 7d, 8bps spread
            "ETH": (0.55, 0.60, 10.0),
            "SOL": (0.75, 0.80, 15.0),
            "XRP": (0.70, 0.75, 12.0),
            "DOGE": (0.90, 0.95, 20.0),
        }
        rv_24h, rv_7d, spread = default_vols.get(asset, (0.60, 0.65, 12.0))
        
        return AssetVolatilityState(
            asset=asset,
            rv_24h=rv_24h,
            rv_7d=rv_7d,
            spread_bps=spread,
            volume_24h=1_000_000_000,
            last_update=time.time(),
        )
    
    def get_volatility(self, asset: str) -> AssetVolatilityState:
        """Get current volatility state for an asset (cached or fresh)."""
        cached = self._get_cached_volatility(asset)
        if cached:
            return cached
        
        fresh = self._fetch_volatility_data(asset)
        if self._cache_lock is not None:
            with self._cache_lock:
                self._volatility_cache[asset] = fresh
        else:
            # Lock disabled - direct access (startup workaround)
            self._volatility_cache[asset] = fresh
        return fresh
    
    def compute_edge_threshold(
        self,
        asset: str,
        timeframe: str,
        override_base: Optional[Decimal] = None,
    ) -> Decimal:
        """Compute dynamic edge threshold for an asset/timeframe.
        
        Formula:
            edge = base_edge * asset_mult * tf_mult * (1 + vol_adjust) * (1 + spread_adjust)
        
        Where:
            - base_edge: Starting edge (~0.8% for BTC)
            - asset_mult: Asset risk multiplier (BTC=1.0, DOGE=1.6)
            - tf_mult: Timeframe multiplier (15m=1.0, annual=2.0)
            - vol_adjust: sqrt(rv_24h / 0.5) - 1 (increase with vol)
            - spread_adjust: spread_bps / 100 * spread_scaling
        
        Args:
            asset: Asset symbol (BTC, ETH, SOL, XRP, DOGE)
            timeframe: Timeframe (15m, 1h, daily, weekly, monthly, annual)
            override_base: Optional base edge override
            
        Returns:
            Dynamic edge threshold as Decimal, clamped to [floor, ceiling]
        """
        asset_upper = asset.upper()
        tf_norm = self._normalize_timeframe(timeframe)
        
        # Get market conditions
        vol_state = self.get_volatility(asset_upper)
        
        # Base components
        base = override_base or self.config.base_edge
        asset_mult = self.config.asset_risk_multipliers.get(asset_upper, Decimal("1.3"))
        tf_mult = self.config.timeframe_multipliers.get(tf_norm, Decimal("1.5"))
        
        # Volatility adjustment: edge scales with sqrt of vol ratio to baseline
        # Baseline vol is 50% annualized
        baseline_vol = 0.50
        vol_ratio = vol_state.rv_24h / baseline_vol
        vol_adjust = Decimal(str(vol_ratio ** 0.5)) - Decimal("1.0")
        vol_adjust = max(Decimal("0"), vol_adjust)  # Only increase, never decrease below base
        
        # Spread adjustment: higher spread requires higher edge
        spread_adjust = Decimal(str(vol_state.spread_bps / 1000)) * self.config.spread_scaling
        
        # Compute dynamic edge
        dynamic_edge = base * asset_mult * tf_mult * (Decimal("1") + vol_adjust) * (Decimal("1") + spread_adjust)
        
        # Clamp to safety bounds
        dynamic_edge = max(self.config.min_edge_floor, min(self.config.max_edge_ceiling, dynamic_edge))
        
        # Round to 4 decimal places
        dynamic_edge = dynamic_edge.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
        
        logger.debug(
            f"Dynamic edge for {asset_upper}/{tf_norm}: {dynamic_edge} "
            f"(base={base}, asset_mult={asset_mult}, tf_mult={tf_mult}, "
            f"vol_adjust={vol_adjust:.3f}, spread_adjust={spread_adjust:.3f})"
        )
        
        return dynamic_edge
    
    def _normalize_timeframe(self, timeframe: str) -> str:
        """Normalize timeframe to canonical label."""
        t = (timeframe or "").strip().lower()
        if t in ("15m", "15min", "fifteen_min"):
            return "15m"
        if t in ("1h", "1hr", "hourly", "hour"):
            return "1h"
        if t in ("daily", "d1", "day", "1d"):
            return "daily"
        if t in ("weekly", "w1", "week"):
            return "weekly"
        if t in ("monthly", "mo", "month"):
            return "monthly"
        if t in ("annual", "yearly", "y1", "year"):
            return "annual"
        return "daily"  # Default
    
    def get_all_thresholds(self) -> Dict[str, Dict[str, Decimal]]:
        """Get all dynamic thresholds for all assets/timeframes."""
        assets = ["BTC", "ETH", "SOL", "XRP", "DOGE"]
        timeframes = ["15m", "1h", "daily", "weekly", "monthly", "annual"]
        
        result: Dict[str, Dict[str, Decimal]] = {}
        for asset in assets:
            result[asset] = {}
            for tf in timeframes:
                result[asset][tf] = self.compute_edge_threshold(asset, tf)
        
        return result
    
    def invalidate_cache(self, asset: Optional[str] = None) -> None:
        """Invalidate volatility cache for an asset or all assets."""
        if self._cache_lock is not None:
            with self._cache_lock:
                if asset:
                    self._volatility_cache.pop(asset.upper(), None)
                else:
                    self._volatility_cache.clear()
        else:
            # Lock disabled - direct access (startup workaround)
            if asset:
                self._volatility_cache.pop(asset.upper(), None)
            else:
                self._volatility_cache.clear()


# Singleton instance
_calibrator_instance: Optional[DynamicEdgeCalibrator] = None
# TEMPORARILY DISABLED: threading.Lock causing deadlock during startup
# TODO: Re-enable lock after startup is stable and investigate proper async synchronization
# _calibrator_lock = threading.Lock()
_calibrator_lock = None  # Disabled to prevent startup hang


def get_dynamic_edge_calibrator() -> DynamicEdgeCalibrator:
    """Get the singleton DynamicEdgeCalibrator instance."""
    global _calibrator_instance
    if _calibrator_instance is None:
        if _calibrator_lock is not None:
            with _calibrator_lock:
                if _calibrator_instance is None:
                    _calibrator_instance = DynamicEdgeCalibrator()
        else:
            # Lock disabled - direct initialization (startup workaround)
            _calibrator_instance = DynamicEdgeCalibrator()
    return _calibrator_instance


def compute_dynamic_edge(asset: str, timeframe: str) -> Decimal:
    """Convenience function to compute edge for an asset/timeframe pair."""
    return get_dynamic_edge_calibrator().compute_edge_threshold(asset, timeframe)
