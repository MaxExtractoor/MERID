"""Toxicity Detection Module for Kalshi 15m Crypto Trading

This module implements detection of predatory trading behaviors and market manipulation:
- VPIN (Volume-Synchronized Probability of Informed Trading)
- Volume Z-score anomaly detection
- Price divergence detection
- Entropy-based market chaos detection

Based on 2026 research on HFT/predatory trading in prediction markets.
"""

from __future__ import annotations

import logging
import math
from collections import deque
from dataclasses import dataclass, field
from typing import Optional, Tuple, List
from datetime import datetime, timezone

import numpy as np

from utils.logger import get_logger

logger = get_logger("merid.event_venues.kalshi.toxicity_detection")


@dataclass
class ToxicityMetrics:
    """Real-time toxicity metrics for a market."""
    
    # VPIN metrics
    vpin: float = 0.0  # Volume-Synchronized Probability of Informed Trading (0-1)
    volume_imbalance: float = 0.0  # Buy-sell volume imbalance (-1 to 1)
    trade_intensity: float = 0.0  # Trades per second
    
    # Volume Z-score
    volume_z_score: float = 0.0  # Z-score of recent volume vs baseline
    volume_baseline: float = 0.0  # Rolling baseline volume
    volume_std: float = 0.0  # Rolling volume std dev
    
    # Price divergence
    price_divergence: float = 0.0  # Price velocity deviation from expected
    price_velocity: float = 0.0  # Rate of price change (cents/second)
    expected_velocity: float = 0.0  # Expected velocity based on recent history
    
    # Entropy metrics
    market_entropy: float = 0.0  # Shannon entropy of price/volume distribution
    signal_energy: float = 0.0  # Signal energy (sum of squared changes)
    
    # Composite scores
    toxicity_score: float = 0.0  # Composite toxicity (0-1)
    anomaly_score: float = 0.0  # Composite anomaly (0-1)
    
    # Flags
    is_toxic: bool = False  # VPIN above threshold
    is_anomalous: bool = False  # Volume Z-score above threshold
    is_divergent: bool = False  # Price divergence detected
    is_chaotic: bool = False  # Entropy above threshold (kill switch trigger)
    
    # Timestamp
    timestamp: float = field(default_factory=lambda: datetime.now(timezone.utc).timestamp())
    
    def to_dict(self) -> dict:
        """Convert to dict for logging/alerting."""
        return {
            "vpin": self.vpin,
            "volume_imbalance": self.volume_imbalance,
            "trade_intensity": self.trade_intensity,
            "volume_z_score": self.volume_z_score,
            "price_divergence": self.price_divergence,
            "price_velocity": self.price_velocity,
            "market_entropy": self.market_entropy,
            "signal_energy": self.signal_energy,
            "toxicity_score": self.toxicity_score,
            "anomaly_score": self.anomaly_score,
            "is_toxic": self.is_toxic,
            "is_anomalous": self.is_anomalous,
            "is_divergent": self.is_divergent,
            "is_chaotic": self.is_chaotic,
            "timestamp": self.timestamp,
        }


class ToxicityDetector:
    """Real-time toxicity detection for Kalshi markets.
    
    Implements VPIN, volume Z-score, price divergence, and entropy detection
    to identify predatory trading and market manipulation.
    """
    
    def __init__(
        self,
        vpin_window_size: int = 50,  # Number of trades for VPIN calculation
        volume_window_size: int = 100,  # Number of trades for volume baseline
        price_window_size: int = 30,  # Number of price points for divergence
        entropy_window_size: int = 60,  # Number of observations for entropy
        vpin_threshold: float = 0.65,  # VPIN threshold for toxic flow
        volume_z_threshold: float = 8.0,  # Z-score threshold for anomaly
        price_divergence_threshold: float = 0.02,  # 2% divergence threshold
        entropy_threshold: float = 2.5,  # Entropy threshold for kill switch
    ):
        self.vpin_window_size = vpin_window_size
        self.volume_window_size = volume_window_size
        self.price_window_size = price_window_size
        self.entropy_window_size = entropy_window_size
        
        self.vpin_threshold = vpin_threshold
        self.volume_z_threshold = volume_z_threshold
        self.price_divergence_threshold = price_divergence_threshold
        self.entropy_threshold = entropy_threshold
        
        # Rolling windows
        self.trade_volumes: deque = deque(maxlen=vpin_window_size)
        self.trade_sides: deque = deque(maxlen=vpin_window_size)  # 1 for buy, -1 for sell
        self.trade_times: deque = deque(maxlen=vpin_window_size)
        
        self.volume_history: deque = deque(maxlen=volume_window_size)
        self.price_history: deque = deque(maxlen=price_window_size)
        self.entropy_history: deque = deque(maxlen=entropy_window_size)
        
        # State
        self.last_price: Optional[float] = None
        self.last_time: Optional[float] = None
        self.baseline_volume: float = 0.0
        self.baseline_std: float = 0.0
        
        logger.info(
            f"[TOXICITY-DETECTOR] Initialized with thresholds: "
            f"VPIN={vpin_threshold}, Volume-Z={volume_z_threshold}, "
            f"Price-Div={price_divergence_threshold}, Entropy={entropy_threshold}"
        )
    
    def update(
        self,
        price_cents: int,
        volume: int,
        side: str,  # "buy" or "sell"
        timestamp: Optional[float] = None,
    ) -> ToxicityMetrics:
        """Update detector with new trade data and compute metrics.
        
        Args:
            price_cents: Trade price in cents
            volume: Trade size in contracts
            side: Trade side ("buy" or "sell")
            timestamp: Trade timestamp (Unix epoch), defaults to now
        
        Returns:
            ToxicityMetrics with all computed metrics
        """
        if timestamp is None:
            timestamp = datetime.now(timezone.utc).timestamp()
        
        # Update rolling windows
        self.trade_volumes.append(volume)
        self.trade_sides.append(1 if side == "buy" else -1)
        self.trade_times.append(timestamp)
        
        self.volume_history.append(volume)
        self.price_history.append(price_cents)
        
        # Compute metrics
        metrics = ToxicityMetrics(timestamp=timestamp)
        
        # VPIN
        metrics.vpin, metrics.volume_imbalance, metrics.trade_intensity = self._compute_vpin()
        
        # Volume Z-score
        metrics.volume_z_score, metrics.volume_baseline, metrics.volume_std = self._compute_volume_z_score()
        
        # Price divergence
        metrics.price_divergence, metrics.price_velocity, metrics.expected_velocity = self._compute_price_divergence()
        
        # Entropy
        metrics.market_entropy, metrics.signal_energy = self._compute_entropy()
        
        # Composite scores
        metrics.toxicity_score = self._compute_toxicity_score(metrics)
        metrics.anomaly_score = self._compute_anomaly_score(metrics)
        
        # Flags
        metrics.is_toxic = metrics.vpin >= self.vpin_threshold
        metrics.is_anomalous = abs(metrics.volume_z_score) >= self.volume_z_threshold
        metrics.is_divergent = abs(metrics.price_divergence) >= self.price_divergence_threshold
        metrics.is_chaotic = metrics.market_entropy >= self.entropy_threshold
        
        # Update state
        self.last_price = price_cents
        self.last_time = timestamp
        
        return metrics
    
    def _compute_vpin(self) -> Tuple[float, float, float]:
        """Compute VPIN (Volume-Synchronized Probability of Informed Trading).
        
        VPIN measures the probability that the current order flow is informed
        (toxic) based on volume imbalance and trade intensity.
        
        Returns:
            (vpin, volume_imbalance, trade_intensity)
        """
        if len(self.trade_volumes) < 10:
            return 0.0, 0.0, 0.0
        
        # Volume imbalance: (buy_vol - sell_vol) / total_vol
        buy_vol = sum(v for v, s in zip(self.trade_volumes, self.trade_sides) if s > 0)
        sell_vol = sum(v for v, s in zip(self.trade_volumes, self.trade_sides) if s < 0)
        total_vol = sum(self.trade_volumes)
        
        if total_vol == 0:
            return 0.0, 0.0, 0.0
        
        volume_imbalance = (buy_vol - sell_vol) / total_vol
        
        # Trade intensity: trades per second
        if len(self.trade_times) >= 2:
            time_span = self.trade_times[-1] - self.trade_times[0]
            if time_span > 0:
                trade_intensity = len(self.trade_times) / time_span
            else:
                trade_intensity = 0.0
        else:
            trade_intensity = 0.0
        
        # VPIN: combines imbalance and intensity
        # High imbalance + high intensity = high VPIN (toxic flow)
        vpin = abs(volume_imbalance) * min(trade_intensity / 10.0, 1.0)
        
        return vpin, volume_imbalance, trade_intensity
    
    def _compute_volume_z_score(self) -> Tuple[float, float, float]:
        """Compute volume Z-score relative to rolling baseline.
        
        Returns:
            (z_score, baseline, std_dev)
        """
        if len(self.volume_history) < 20:
            return 0.0, 0.0, 0.0
        
        volumes = list(self.volume_history)
        baseline = np.mean(volumes)
        std = np.std(volumes)
        
        if std == 0:
            return 0.0, baseline, 0.0
        
        current_volume = volumes[-1]
        z_score = (current_volume - baseline) / std
        
        return z_score, baseline, std
    
    def _compute_price_divergence(self) -> Tuple[float, float, float]:
        """Compute price divergence from expected velocity.
        
        Returns:
            (divergence, current_velocity, expected_velocity)
        """
        if len(self.price_history) < 5 or self.last_time is None:
            return 0.0, 0.0, 0.0
        
        prices = list(self.price_history)
        
        # Current velocity (cents/second)
        current_price = prices[-1]
        prev_price = prices[-2]
        time_delta = self.trade_times[-1] - self.trade_times[-2] if len(self.trade_times) >= 2 else 1.0
        
        if time_delta == 0:
            time_delta = 1.0
        
        current_velocity = (current_price - prev_price) / time_delta
        
        # Expected velocity (average of recent velocities)
        velocities = []
        for i in range(2, min(len(prices), 6)):
            if i < len(self.trade_times):
                dt = self.trade_times[-1] - self.trade_times[-i]
                if dt > 0:
                    velocities.append((prices[-1] - prices[-i]) / dt)
        
        if velocities:
            expected_velocity = np.mean(velocities)
        else:
            expected_velocity = 0.0
        
        # Divergence: difference from expected
        divergence = current_velocity - expected_velocity
        
        return divergence, current_velocity, expected_velocity
    
    def _compute_entropy(self) -> Tuple[float, float]:
        """Compute Shannon entropy of price/volume distribution.
        
        Higher entropy = more chaotic market = potential manipulation.
        
        Returns:
            (entropy, signal_energy)
        """
        if len(self.price_history) < 10:
            return 0.0, 0.0
        
        prices = list(self.price_history)
        
        # Signal energy: sum of squared changes
        changes = [abs(prices[i] - prices[i-1]) for i in range(1, len(prices))]
        signal_energy = sum(c**2 for c in changes)
        
        # Entropy: based on price change distribution
        if len(changes) < 2:
            return 0.0, signal_energy
        
        # Normalize changes to probabilities
        total_change = sum(changes)
        if total_change == 0:
            return 0.0, signal_energy
        
        probs = [c / total_change for c in changes]
        
        # Shannon entropy: -sum(p * log(p))
        entropy = -sum(p * math.log(p) if p > 0 else 0 for p in probs)
        
        return entropy, signal_energy
    
    def _compute_toxicity_score(self, metrics: ToxicityMetrics) -> float:
        """Compute composite toxicity score (0-1).
        
        Combines VPIN, volume imbalance, and trade intensity.
        """
        # Weighted combination
        vpin_weight = 0.5
        imbalance_weight = 0.3
        intensity_weight = 0.2
        
        normalized_imbalance = abs(metrics.volume_imbalance)
        normalized_intensity = min(metrics.trade_intensity / 10.0, 1.0)
        
        score = (
            vpin_weight * metrics.vpin +
            imbalance_weight * normalized_imbalance +
            intensity_weight * normalized_intensity
        )
        
        return min(score, 1.0)
    
    def _compute_anomaly_score(self, metrics: ToxicityMetrics) -> float:
        """Compute composite anomaly score (0-1).
        
        Combines volume Z-score, price divergence, and entropy.
        """
        # Weighted combination
        volume_weight = 0.4
        divergence_weight = 0.3
        entropy_weight = 0.3
        
        normalized_volume_z = min(abs(metrics.volume_z_score) / 10.0, 1.0)
        normalized_divergence = min(abs(metrics.price_divergence) / 0.05, 1.0)
        normalized_entropy = min(metrics.market_entropy / 3.0, 1.0)
        
        score = (
            volume_weight * normalized_volume_z +
            divergence_weight * normalized_divergence +
            entropy_weight * normalized_entropy
        )
        
        return min(score, 1.0)
    
    def should_block_trading(self, metrics: ToxicityMetrics) -> Tuple[bool, str]:
        """Determine if trading should be blocked based on toxicity.
        
        Returns:
            (should_block, reason)
        """
        if metrics.is_chaotic:
            return True, f"Market entropy too high: {metrics.market_entropy:.3f} >= {self.entropy_threshold}"
        
        if metrics.is_toxic and metrics.toxicity_score > 0.8:
            return True, f"Toxic flow detected: VPIN={metrics.vpin:.3f}, score={metrics.toxicity_score:.3f}"
        
        if metrics.is_anomalous and abs(metrics.volume_z_score) > 12.0:
            return True, f"Extreme volume anomaly: Z-score={metrics.volume_z_score:.1f}"
        
        return False, "Trading allowed"
    
    def get_spread_multiplier(self, metrics: ToxicityMetrics) -> float:
        """Get spread multiplier based on toxicity.
        
        Higher toxicity = wider spreads to compensate for adverse selection.
        
        Returns:
            Multiplier (1.0 = normal, >1.0 = wider spread)
        """
        if metrics.is_toxic:
            # Toxic flow: widen spreads significantly
            base_multiplier = 2.5
            # Scale by toxicity score
            return base_multiplier * (1.0 + metrics.toxicity_score)
        elif metrics.is_anomalous:
            # Anomalous volume: moderate widening
            return 1.5
        elif metrics.is_divergent:
            # Price divergence: slight widening
            return 1.2
        else:
            # Normal conditions
            return 1.0


# Global detector instances per ticker
_detectors: dict[str, ToxicityDetector] = {}


def get_toxicity_detector(
    ticker: str,
    vpin_threshold: float = 0.65,
    volume_z_threshold: float = 8.0,
    price_divergence_threshold: float = 0.02,
    entropy_threshold: float = 2.5,
) -> ToxicityDetector:
    """Get or create toxicity detector for a ticker.
    
    Args:
        ticker: Market ticker
        vpin_threshold: VPIN threshold for toxic flow
        volume_z_threshold: Z-score threshold for anomaly
        price_divergence_threshold: Price divergence threshold
        entropy_threshold: Entropy threshold for kill switch
    
    Returns:
        ToxicityDetector instance
    """
    if ticker not in _detectors:
        _detectors[ticker] = ToxicityDetector(
            vpin_threshold=vpin_threshold,
            volume_z_threshold=volume_z_threshold,
            price_divergence_threshold=price_divergence_threshold,
            entropy_threshold=entropy_threshold,
        )
        logger.info(f"[TOXICITY-DETECTOR] Created detector for {ticker}")
    
    return _detectors[ticker]


def reset_toxicity_detectors() -> None:
    """Reset all toxicity detectors (clear state)."""
    global _detectors
    _detectors.clear()
    logger.info("[TOXICITY-DETECTOR] Reset all detectors")
