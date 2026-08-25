"""
Rolling Correlation Calculator

Computes rolling correlations from historical price data to replace
static hardcoded correlation values with dynamic, market-responsive metrics.

CRITICAL FIX (2026-07-23): Added config logging for audit trail.
"""

from __future__ import annotations

import time
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
import numpy as np

from utils.logger import get_logger

logger = get_logger("merid.prediction.rolling_correlation")


@dataclass
class CorrelationResult:
    """Result of correlation calculation with metadata."""
    correlation: float
    confidence: float  # 0.0-1.0 based on sample size
    sample_size: int
    timestamp: float


class RollingCorrelationCalculator:
    """
    Computes rolling correlations from historical price data.
    
    This replaces static hardcoded correlation values with dynamic
    calculations that adapt to changing market conditions.
    
    Features:
    - Rolling window of configurable duration
    - Minimum sample size requirements
    - Confidence interval estimation
    - Automatic pruning of old data
    """
    
    def __init__(self, window_days: int = 30, min_samples: int = 100):
        """
        Initialize the rolling correlation calculator.
        
        Args:
            window_days: Number of days of historical data to use
            min_samples: Minimum number of data points required for calculation
        """
        self.window_days = window_days
        self.min_samples = min_samples
        self.price_history: Dict[str, List[Tuple[float, float]]] = {}
        self._window_seconds = window_days * 24 * 3600
        
        # CRITICAL FIX (2026-07-23): Log config on startup
        self._log_config()
    
    def _log_config(self):
        """Log configuration for audit trail."""
        logger.info(
            f"[ROLLING-CORRELATION-CONFIG] window_days={self.window_days} "
            f"min_samples={self.min_samples} "
            f"window_seconds={self._window_seconds}"
        )
    
    def update_price(self, asset: str, price: float, timestamp: float):
        """
        Add a price point to the history.
        
        Args:
            asset: Asset symbol (e.g., "BTC", "ETH")
            price: Price value
            timestamp: Unix timestamp
        """
        self.price_history.setdefault(asset, []).append((timestamp, price))
        self._prune_old_data(asset, timestamp)
    
    def _prune_old_data(self, asset: str, current_timestamp: float):
        """
        Remove data points older than the rolling window.
        
        Args:
            asset: Asset symbol
            current_timestamp: Current timestamp for pruning
        """
        if asset not in self.price_history:
            return
        
        cutoff_time = current_timestamp - self._window_seconds
        self.price_history[asset] = [
            (ts, price) for ts, price in self.price_history[asset]
            if ts >= cutoff_time
        ]
    
    def compute_correlation(self, asset1: str, asset2: str) -> Optional[float]:
        """
        Compute Pearson correlation between two assets.
        
        Args:
            asset1: First asset symbol
            asset2: Second asset symbol
            
        Returns:
            Correlation coefficient (-1.0 to 1.0), or None if insufficient data
        """
        if asset1 not in self.price_history or asset2 not in self.price_history:
            logger.debug(
                f"Insufficient history for correlation: {asset1} or {asset2} not in history"
            )
            return None
        
        history1 = self.price_history[asset1]
        history2 = self.price_history[asset2]
        
        if len(history1) < self.min_samples or len(history2) < self.min_samples:
            logger.debug(
                f"Insufficient samples for correlation: "
                f"{asset1}={len(history1)}, {asset2}={len(history2)} "
                f"(min={self.min_samples})"
            )
            return None
        
        # Align timestamps and compute correlation
        aligned = self._align_series(history1, history2)
        
        if len(aligned) < self.min_samples:
            logger.debug(
                f"Insufficient aligned samples for correlation: {len(aligned)} "
                f"(min={self.min_samples})"
            )
            return None
        
        prices1 = np.array([p for _, p in aligned[0]])
        prices2 = np.array([p for _, p in aligned[1]])
        
        # Compute Pearson correlation
        correlation = self._compute_pearson_correlation(prices1, prices2)
        
        logger.debug(
            f"Correlation {asset1}-{asset2}: {correlation:.3f} "
            f"(n={len(aligned)})"
        )
        
        return correlation
    
    def _align_series(
        self,
        history1: List[Tuple[float, float]],
        history2: List[Tuple[float, float]],
        tolerance_seconds: float = 5.0
    ) -> Tuple[List[Tuple[float, float]], List[Tuple[float, float]]]:
        """
        Align two price series by timestamp.
        
        Args:
            history1: First price history [(timestamp, price), ...]
            history2: Second price history [(timestamp, price), ...]
            tolerance_seconds: Maximum timestamp difference for alignment
            
        Returns:
            Tuple of aligned price series
        """
        # Convert to dictionaries for faster lookup
        dict1 = {ts: price for ts, price in history1}
        dict2 = {ts: price for ts, price in history2}
        
        # Find common timestamps within tolerance
        aligned1 = []
        aligned2 = []
        
        for ts1, price1 in history1:
            # Find closest timestamp in history2
            for ts2, price2 in history2:
                if abs(ts1 - ts2) <= tolerance_seconds:
                    aligned1.append((ts1, price1))
                    aligned2.append((ts2, price2))
                    break
        
        return aligned1, aligned2
    
    def _compute_pearson_correlation(self, x: np.ndarray, y: np.ndarray) -> float:
        """
        Compute Pearson correlation coefficient.
        
        Args:
            x: First array
            y: Second array
            
        Returns:
            Correlation coefficient (-1.0 to 1.0)
        """
        if len(x) != len(y) or len(x) < 2:
            return 0.0
        
        # Compute correlation
        mean_x = np.mean(x)
        mean_y = np.mean(y)
        
        covariance = np.sum((x - mean_x) * (y - mean_y))
        std_x = np.sqrt(np.sum((x - mean_x) ** 2))
        std_y = np.sqrt(np.sum((y - mean_y) ** 2))
        
        if std_x == 0 or std_y == 0:
            return 0.0
        
        correlation = covariance / (std_x * std_y)
        
        # Clamp to valid range
        return max(-1.0, min(1.0, correlation))
    
    def get_correlation_with_confidence(
        self,
        asset1: str,
        asset2: str
    ) -> Optional[CorrelationResult]:
        """
        Compute correlation with confidence interval.
        
        Args:
            asset1: First asset symbol
            asset2: Second asset symbol
            
        Returns:
            CorrelationResult with correlation, confidence, and metadata
        """
        correlation = self.compute_correlation(asset1, asset2)
        
        if correlation is None:
            return None
        
        # Estimate confidence based on sample size
        if asset1 in self.price_history and asset2 in self.price_history:
            history1 = self.price_history[asset1]
            history2 = self.price_history[asset2]
            aligned = self._align_series(history1, history2)
            sample_size = len(aligned[0])
            
            # Simple confidence estimation based on sample size
            # More samples = higher confidence
            confidence = min(1.0, sample_size / (2 * self.min_samples))
        else:
            confidence = 0.0
            sample_size = 0
        
        return CorrelationResult(
            correlation=correlation,
            confidence=confidence,
            sample_size=sample_size,
            timestamp=time.time()
        )
    
    def get_all_correlations(self, base_asset: str) -> Dict[str, Optional[float]]:
        """
        Compute correlations between base asset and all other assets.
        
        Args:
            base_asset: Base asset symbol
            
        Returns:
            Dictionary mapping asset -> correlation
        """
        correlations = {}
        
        for asset in self.price_history.keys():
            if asset != base_asset:
                correlations[asset] = self.compute_correlation(base_asset, asset)
        
        return correlations
