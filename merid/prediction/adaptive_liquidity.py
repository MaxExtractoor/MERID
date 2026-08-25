"""
Adaptive Liquidity Calculator

Computes adaptive liquidity thresholds from recent market depth observations
to replace static hardcoded thresholds with dynamic, market-responsive metrics.

CRITICAL FIX (2026-07-23): Added config logging for audit trail.
"""

from __future__ import annotations

import time
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
import numpy as np

from utils.logger import get_logger

logger = get_logger("merid.prediction.adaptive_liquidity")


@dataclass
class LiquidityThreshold:
    """Adaptive liquidity threshold with metadata."""
    threshold: int
    percentile: float
    sample_size: int
    timestamp: float


class AdaptiveLiquidityCalculator:
    """
    Computes adaptive liquidity thresholds from recent depth observations.
    
    This replaces static liquidity thresholds with dynamic calculations
    that adapt to changing market conditions and time-of-day patterns.
    
    Features:
    - Rolling window of depth observations
    - Percentile-based threshold calculation
    - Time-of-day multipliers
    - Minimum sample size requirements
    """
    
    def __init__(self, window_minutes: int = 60, percentile: float = 0.8):
        """
        Initialize the adaptive liquidity calculator.
        
        Args:
            window_minutes: Number of minutes of historical data to use
            percentile: Percentile for threshold calculation (0.0-1.0)
        """
        self.window_minutes = window_minutes
        self.percentile = percentile
        self.depth_history: Dict[str, List[Tuple[float, int]]] = {}
        self._window_seconds = window_minutes * 60
        
        # CRITICAL FIX (2026-07-23): Log config on startup
        self._log_config()
    
    def _log_config(self):
        """Log configuration for audit trail."""
        logger.info(
            f"[ADAPTIVE-LIQUIDITY-CONFIG] window_minutes={self.window_minutes} "
            f"percentile={self.percentile} "
            f"window_seconds={self._window_seconds}"
        )
    
    def update_depth(self, asset: str, depth: int, timestamp: float):
        """
        Add a depth observation to the history.
        
        Args:
            asset: Asset symbol
            depth: Market depth (number of contracts)
            timestamp: Unix timestamp
        """
        self.depth_history.setdefault(asset, []).append((timestamp, depth))
        self._prune_old_data(asset, timestamp)
    
    def _prune_old_data(self, asset: str, current_timestamp: float):
        """
        Remove data points older than the rolling window.
        
        Args:
            asset: Asset symbol
            current_timestamp: Current timestamp for pruning
        """
        if asset not in self.depth_history:
            return
        
        cutoff_time = current_timestamp - self._window_seconds
        self.depth_history[asset] = [
            (ts, depth) for ts, depth in self.depth_history[asset]
            if ts >= cutoff_time
        ]
    
    def get_threshold(self, asset: str) -> Optional[int]:
        """
        Get adaptive liquidity threshold for an asset.
        
        Args:
            asset: Asset symbol
            
        Returns:
            Threshold value (integer), or None if insufficient data
        """
        if asset not in self.depth_history:
            logger.debug(f"No depth history for {asset}")
            return None
        
        history = self.depth_history[asset]
        
        if len(history) < 10:
            logger.debug(
                f"Insufficient depth observations for {asset}: {len(history)} (min=10)"
            )
            return None
        
        # Extract depth values
        depths = [depth for _, depth in history]
        
        # Compute percentile threshold
        threshold = int(np.percentile(depths, self.percentile * 100))
        
        # Apply time-of-day multiplier
        multiplier = self._get_time_of_day_multiplier(time.time())
        adjusted_threshold = int(threshold * multiplier)
        
        logger.debug(
            f"Liquidity threshold for {asset}: {adjusted_threshold} "
            f"(base={threshold}, multiplier={multiplier:.2f}, n={len(depths)})"
        )
        
        return adjusted_threshold
    
    def _get_time_of_day_multiplier(self, timestamp: float) -> float:
        """
        Get liquidity multiplier based on time of day.
        
        Args:
            timestamp: Unix timestamp
            
        Returns:
            Multiplier (0.0-1.0)
        """
        from datetime import datetime, timezone
        
        hour = datetime.fromtimestamp(timestamp, timezone.utc).hour
        
        # US hours (14:00-20:00 UTC) = highest liquidity
        if 14 <= hour < 20:
            return 1.0
        # European hours (8:00-14:00 UTC) = medium liquidity
        elif 8 <= hour < 14:
            return 0.8
        # Asian hours (0:00-8:00 UTC) = lower liquidity
        elif 0 <= hour < 8:
            return 0.6
        # Weekend = lowest liquidity
        else:
            return 0.5
    
    def get_threshold_with_metadata(self, asset: str) -> Optional[LiquidityThreshold]:
        """
        Get threshold with full metadata.
        
        Args:
            asset: Asset symbol
            
        Returns:
            LiquidityThreshold with threshold and metadata
        """
        if asset not in self.depth_history:
            return None
        
        history = self.depth_history[asset]
        
        if len(history) < 10:
            return None
        
        depths = [depth for _, depth in history]
        threshold = int(np.percentile(depths, self.percentile * 100))
        multiplier = self._get_time_of_day_multiplier(time.time())
        adjusted_threshold = int(threshold * multiplier)
        
        return LiquidityThreshold(
            threshold=adjusted_threshold,
            percentile=self.percentile,
            sample_size=len(depths),
            timestamp=time.time()
        )
    
    def get_all_thresholds(self) -> Dict[str, Optional[int]]:
        """
        Get thresholds for all assets.
        
        Returns:
            Dictionary mapping asset -> threshold
        """
        thresholds = {}
        
        for asset in self.depth_history.keys():
            thresholds[asset] = self.get_threshold(asset)
        
        return thresholds
    
    def get_depth_statistics(self, asset: str) -> Optional[Dict]:
        """
        Get depth statistics for an asset.
        
        Args:
            asset: Asset symbol
            
        Returns:
            Dictionary with depth statistics
        """
        if asset not in self.depth_history:
            return None
        
        history = self.depth_history[asset]
        
        if len(history) < 10:
            return None
        
        depths = [depth for _, depth in history]
        
        return {
            "mean": np.mean(depths),
            "std": np.std(depths),
            "min": np.min(depths),
            "max": np.max(depths),
            "median": np.median(depths),
            "p25": np.percentile(depths, 25),
            "p75": np.percentile(depths, 75),
            "sample_size": len(depths),
        }
