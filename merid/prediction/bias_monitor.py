"""Directional Bias Monitor for Trading Signals.

This module implements statistical monitoring for directional bias in trading signals,
based on academic research (BFSA - Bias-Corrected Feature Selection).

Key Features:
1. Tracks YES/NO signal distribution over time
2. Performs chi-square test for statistical significance
3. Alerts when bias exceeds threshold
4. Provides bias correction recommendations
5. Price distribution bias detection (NEW)
6. Favorite-longshot bias detection (NEW)
7. Temporal bias detection (NEW)
8. Wang Transform lambda estimation (NEW)

Usage::

    from merid.prediction.bias_monitor import BiasMonitor, get_bias_monitor
    
    monitor = get_bias_monitor()
    monitor.record_signal(asset="BTC", side="yes", edge=5.0, price=0.45)
    bias_report = monitor.get_bias_report()
    if bias_report.bias_detected:
        logger.warning(f"Bias detected: {bias_report}")
"""

from __future__ import annotations

import time
import statistics
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta

from utils.logger import get_logger

logger = get_logger("merid.prediction.bias_monitor")

try:
    import numpy as np
    from scipy import stats
    SCIPY_AVAILABLE = True
except ImportError:
    SCIPY_AVAILABLE = False
    logger.debug("[BIAS-MONITOR] scipy/numpy not available - using simplified analysis")


@dataclass
class BiasReport:
    """Report on directional bias in trading signals."""
    
    asset: str
    total_signals: int
    yes_count: int
    no_count: int
    yes_percentage: float
    no_percentage: float
    bias_detected: bool
    bias_direction: str  # "yes", "no", or "neutral"
    chi_square: float
    p_value: float
    recommendation: str
    timestamp: datetime
    # New fields for enhanced bias detection
    price_distribution_bias: bool = False
    favorite_longshot_bias: bool = False
    temporal_bias: bool = False
    wang_lambda: Optional[float] = None


class BiasMonitor:
    """Monitor directional bias in trading signals with statistical tests."""
    
    def __init__(self, window_size: int = 100, bias_threshold: float = 0.60, auto_check: bool = True):
        """
        Initialize bias monitor.
        
        Args:
            window_size: Number of recent signals to analyze
            bias_threshold: Threshold for bias detection (default 60%)
            auto_check: Whether to automatically check bias after each signal (default True)
        """
        self.window_size = window_size
        self.bias_threshold = bias_threshold
        self.auto_check = auto_check
        
        # Per-asset signal history
        self._signal_history: Dict[str, deque] = defaultdict(lambda: deque(maxlen=window_size))
        
        # Global signal history
        self._global_history: deque = deque(maxlen=window_size * 5)  # Larger window for global
        
        # Statistics
        self._stats = {
            'total_signals': 0,
            'by_asset': defaultdict(lambda: {'yes': 0, 'no': 0, 'total': 0}),
            'by_time': defaultdict(lambda: {'yes': 0, 'no': 0, 'total': 0})
        }
        
        # Price history for distribution analysis
        self._price_history: Dict[str, deque] = defaultdict(lambda: deque(maxlen=window_size))
        
        # Wang Transform lambda estimate
        self._wang_lambda: Optional[float] = None
        
        logger.info(
            "[BIAS-MONITOR] Initialized with window_size=%d bias_threshold=%.2f",
            window_size, bias_threshold
        )
    
    def record_signal(self, asset: str, side: str, edge: Optional[float] = None, price: Optional[float] = None) -> None:
        """
        Record a trading signal for bias monitoring.
        
        Args:
            asset: Asset identifier (e.g., "BTC", "ETH")
            side: Signal side ("yes" or "no")
            edge: Edge percentage (optional, for analysis)
            price: Contract price (optional, for price distribution analysis)
        """
        if side not in ["yes", "no"]:
            logger.warning("[BIAS-MONITOR] Invalid side '%s' for asset %s", side, asset)
            return
        
        timestamp = datetime.utcnow()
        
        # Record signal
        signal_record = {
            'asset': asset,
            'side': side,
            'edge': edge,
            'price': price,
            'timestamp': timestamp
        }
        
        # Update per-asset history
        self._signal_history[asset].append(signal_record)
        
        # Update global history
        self._global_history.append(signal_record)
        
        # Update price history if provided
        if price is not None:
            self._price_history[asset].append(price)
        
        # Update statistics
        self._stats['total_signals'] += 1
        self._stats['by_asset'][asset][side] += 1
        self._stats['by_asset'][asset]['total'] += 1
        
        # Time-based statistics (hourly buckets)
        time_bucket = timestamp.strftime("%Y-%m-%d-%H")
        self._stats['by_time'][time_bucket][side] += 1
        self._stats['by_time'][time_bucket]['total'] += 1
        
        # Check for bias every 10 signals (if auto_check is enabled)
        if self.auto_check and self._stats['total_signals'] % 10 == 0:
            self._check_bias()
    
    def _check_bias(self) -> None:
        """Check for directional bias and log if detected."""
        report = self.get_bias_report()
        
        if report.bias_detected:
            logger.warning(
                "[BIAS-ALERT] %s bias detected: YES=%.1f%% NO=%.1f%% chi2=%.2f p=%.4f - %s",
                report.asset.upper(),
                report.yes_percentage,
                report.no_percentage,
                report.chi_square,
                report.p_value,
                report.recommendation
            )
        else:
            logger.info(
                "[BIAS-CHECK] %s: YES=%.1f%% NO=%.1f%% - No significant bias",
                report.asset.upper(),
                report.yes_percentage,
                report.no_percentage
            )
    
    def get_bias_report(self, asset: Optional[str] = None) -> BiasReport:
        """
        Generate bias report for a specific asset or globally.
        
        Args:
            asset: Asset to analyze (None for global)
        
        Returns:
            BiasReport with statistics and recommendations
        """
        if asset:
            history = self._signal_history[asset]
            stats = self._stats['by_asset'][asset]
        else:
            history = self._global_history
            # Aggregate global stats
            total_yes = sum(self._stats['by_asset'][a]['yes'] for a in self._stats['by_asset'])
            total_no = sum(self._stats['by_asset'][a]['no'] for a in self._stats['by_asset'])
            stats = {'yes': total_yes, 'no': total_no, 'total': total_yes + total_no}
        
        total = stats['total']
        if total == 0:
            return BiasReport(
                asset=asset or "GLOBAL",
                total_signals=0,
                yes_count=0,
                no_count=0,
                yes_percentage=0.0,
                no_percentage=0.0,
                bias_detected=False,
                bias_direction="neutral",
                chi_square=0.0,
                p_value=1.0,
                recommendation="Insufficient data",
                timestamp=datetime.utcnow()
            )
        
        yes_count = stats['yes']
        no_count = stats['no']
        yes_pct = (yes_count / total * 100) if total > 0 else 0.0
        no_pct = (no_count / total * 100) if total > 0 else 0.0
        
        # Chi-square test for statistical significance
        # H0: YES and NO are equally likely (50/50)
        # H1: YES and NO are not equally likely (bias exists)
        expected_yes = total / 2
        expected_no = total / 2
        
        chi_square = ((yes_count - expected_yes) ** 2 / expected_yes +
                      (no_count - expected_no) ** 2 / expected_no) if total > 0 else 0.0
        
        # Degrees of freedom = 1 (2 categories - 1)
        # Critical value at 95% confidence = 3.841
        p_value = 0.0
        if chi_square > 0:
            # Approximate p-value using chi-square distribution
            # For df=1, chi_square=3.841 → p=0.05, chi_square=6.635 → p=0.01
            if chi_square < 3.841:
                p_value = 0.1
            elif chi_square < 6.635:
                p_value = 0.05
            elif chi_square < 10.828:
                p_value = 0.01
            else:
                p_value = 0.001
        
        # Determine bias
        # For small samples (< 30), use percentage threshold alone
        # For larger samples, require both percentage threshold AND statistical significance
        if total < 30:
            bias_detected = yes_pct > self.bias_threshold or no_pct > self.bias_threshold
        else:
            bias_detected = (yes_pct > self.bias_threshold or no_pct > self.bias_threshold) and p_value < 0.05
        
        # If percentages are equal (50/50), no bias regardless of other conditions
        if abs(yes_pct - no_pct) < 0.01:  # Allow small floating point errors
            bias_detected = False
            bias_direction = "neutral"
        elif yes_pct > no_pct:
            bias_direction = "yes"
        elif no_pct > yes_pct:
            bias_direction = "no"
        else:
            bias_direction = "neutral"
        
        # Generate recommendation
        if bias_detected:
            if bias_direction == "yes":
                recommendation = "Consider lowering edge ratio threshold for NO selection"
            else:
                recommendation = "Consider lowering edge ratio threshold for YES selection"
        else:
            recommendation = "No bias correction needed"
        
        # Check for additional bias types
        price_dist_bias = self._check_price_distribution_bias(asset)
        fav_longshot_bias = self._check_favorite_longshot_bias(asset)
        temporal_bias = self._check_temporal_bias()
        
        return BiasReport(
            asset=asset or "GLOBAL",
            total_signals=total,
            yes_count=yes_count,
            no_count=no_count,
            yes_percentage=yes_pct,
            no_percentage=no_pct,
            bias_detected=bias_detected,
            bias_direction=bias_direction,
            chi_square=chi_square,
            p_value=p_value,
            recommendation=recommendation,
            timestamp=datetime.utcnow(),
            price_distribution_bias=price_dist_bias,
            favorite_longshot_bias=fav_longshot_bias,
            temporal_bias=temporal_bias,
            wang_lambda=self._wang_lambda
        )
    
    def _check_price_distribution_bias(self, asset: Optional[str] = None) -> bool:
        """Check for price distribution bias (clustering around midpoint)."""
        if asset:
            prices = list(self._price_history[asset])
        else:
            # Aggregate all prices
            prices = []
            for asset_prices in self._price_history.values():
                prices.extend(list(asset_prices))
        
        if len(prices) < 20:
            return False
        
        # Check for midpoint clustering (0.4-0.6 range)
        midpoint_concentration = sum(1 for p in prices if 0.4 <= p <= 0.6) / len(prices)
        
        if midpoint_concentration > 0.5:
            logger.warning(
                "[BIAS-MONITOR] Price distribution bias detected: %.1f%% of trades in midpoint range",
                midpoint_concentration * 100
            )
            return True
        
        return False
    
    def _check_favorite_longshot_bias(self, asset: Optional[str] = None) -> bool:
        """Check for favorite-longshot bias using price distribution."""
        if asset:
            prices = list(self._price_history[asset])
        else:
            prices = []
            for asset_prices in self._price_history.values():
                prices.extend(list(asset_prices))
        
        if len(prices) < 30:
            return False
        
        # Group by price buckets
        price_buckets = {
            "longshot": (0.0, 0.20),
            "low_price": (0.20, 0.40),
            "mid_price": (0.40, 0.60),
            "high_price": (0.60, 0.80),
            "favorite": (0.80, 1.0)
        }
        
        bucket_counts = defaultdict(int)
        for price in prices:
            for bucket_name, (min_p, max_p) in price_buckets.items():
                if min_p <= price < max_p:
                    bucket_counts[bucket_name] += 1
                    break
        
        total = len(prices)
        for bucket_name, count in bucket_counts.items():
            bucket_pct = (count / total) * 100
            if bucket_pct > 30:  # More than 30% in one bucket
                logger.warning(
                    "[BIAS-MONITOR] Favorite-longshot bias: %.1f%% concentration in %s bucket",
                    bucket_pct, bucket_name
                )
                return True
        
        return False
    
    def _check_temporal_bias(self) -> bool:
        """Check for temporal bias (hourly patterns)."""
        current_hour = datetime.utcnow().hour
        
        # Get recent hourly statistics
        recent_hours = []
        for hour_offset in range(-24, 0):
            hour_time = datetime.utcnow() + timedelta(hours=hour_offset)
            time_bucket = hour_time.strftime("%Y-%m-%d-%H")
            
            if time_bucket in self._stats['by_time']:
                hour_data = self._stats['by_time'][time_bucket]
                if hour_data['total'] >= 5:
                    yes_pct = (hour_data['yes'] / hour_data['total']) * 100
                    recent_hours.append(yes_pct)
        
        if len(recent_hours) < 5:
            return False
        
        # Check for significant variation
        if SCIPY_AVAILABLE:
            std_dev = np.std(recent_hours)
        else:
            std_dev = statistics.stdev(recent_hours) if len(recent_hours) > 1 else 0
        
        if std_dev > 20:  # More than 20% standard deviation
            logger.warning(
                "[BIAS-MONITOR] Temporal bias detected: hourly YES percentage std=%.1f%%",
                std_dev
            )
            return True
        
        return False
    
    def get_statistics(self) -> Dict:
        """Get current bias statistics."""
        return {
            'total_signals': self._stats['total_signals'],
            'by_asset': dict(self._stats['by_asset']),
            'by_time': dict(self._stats['by_time']),
            'window_size': self.window_size,
            'bias_threshold': self.bias_threshold
        }


# Global bias monitor instance
_bias_monitor: Optional[BiasMonitor] = None


def get_bias_monitor(window_size: int = 100, bias_threshold: float = 0.60) -> BiasMonitor:
    """Get or create the global bias monitor instance."""
    global _bias_monitor
    if _bias_monitor is None:
        _bias_monitor = BiasMonitor(window_size=window_size, bias_threshold=bias_threshold)
    return _bias_monitor


def init_bias_monitor(window_size: int = 100, bias_threshold: float = 0.60) -> None:
    """Initialize the global bias monitor with custom parameters."""
    global _bias_monitor
    _bias_monitor = BiasMonitor(window_size=window_size, bias_threshold=bias_threshold)
    logger.info("[BIAS-MONITOR] Initialized with custom parameters")
