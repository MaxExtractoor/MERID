"""
MERID-OPS Information Latency Mapping

Phase 1.4 of Master Build Directive

Implements:
- Oracle latency tracking
- Exchange update delays
- Social/news propagation delay
- Alpha decay vs latency analysis

This module answers: "How stale is our information?"

Stale information = stale decisions = capital loss.
"""

from __future__ import annotations

import time
import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple
import numpy as np
from collections import deque

from utils.logger import get_logger

logger = get_logger("ops.information_latency")


class InformationSource(Enum):
    """Types of information sources."""
    EXCHANGE_PRICE = "exchange_price"
    EXCHANGE_ORDERBOOK = "exchange_orderbook"
    ORACLE_CHAINLINK = "oracle_chainlink"
    ORACLE_PYTH = "oracle_pyth"
    ORACLE_UMA = "oracle_uma"
    NEWS_FEED = "news_feed"
    SOCIAL_TWITTER = "social_twitter"
    SOCIAL_REDDIT = "social_reddit"
    ON_CHAIN = "on_chain"
    PREDICTION_MARKET = "prediction_market"


class LatencyClass(Enum):
    """Latency classification."""
    REALTIME = "realtime"        # < 100ms
    FAST = "fast"                # 100ms - 1s
    MODERATE = "moderate"        # 1s - 10s
    SLOW = "slow"                # 10s - 60s
    STALE = "stale"              # > 60s
    DEAD = "dead"                # No updates


@dataclass
class LatencyMeasurement:
    """A single latency measurement."""
    source: InformationSource
    measured_latency_ms: float
    timestamp: float
    data_timestamp: float  # When the data was generated at source
    propagation_delay_ms: float  # Time from source to MERID
    processing_delay_ms: float  # Time to process after receipt
    
    def total_latency_ms(self) -> float:
        return self.propagation_delay_ms + self.processing_delay_ms
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "source": self.source.value,
            "measured_latency_ms": round(self.measured_latency_ms, 2),
            "timestamp": self.timestamp,
            "data_timestamp": self.data_timestamp,
            "propagation_delay_ms": round(self.propagation_delay_ms, 2),
            "processing_delay_ms": round(self.processing_delay_ms, 2),
            "total_latency_ms": round(self.total_latency_ms(), 2),
        }


@dataclass
class SourceLatencyProfile:
    """Latency profile for an information source."""
    source: InformationSource
    
    # Statistics
    avg_latency_ms: float = 0.0
    p50_latency_ms: float = 0.0
    p95_latency_ms: float = 0.0
    p99_latency_ms: float = 0.0
    max_latency_ms: float = 0.0
    min_latency_ms: float = float('inf')
    
    # Reliability
    update_frequency_hz: float = 0.0
    last_update: float = 0.0
    missed_updates: int = 0
    total_updates: int = 0
    
    # Classification
    latency_class: LatencyClass = LatencyClass.DEAD
    is_healthy: bool = False
    
    # Alpha decay
    estimated_alpha_decay_per_second: float = 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "source": self.source.value,
            "avg_latency_ms": round(self.avg_latency_ms, 2),
            "p50_latency_ms": round(self.p50_latency_ms, 2),
            "p95_latency_ms": round(self.p95_latency_ms, 2),
            "p99_latency_ms": round(self.p99_latency_ms, 2),
            "max_latency_ms": round(self.max_latency_ms, 2),
            "min_latency_ms": round(self.min_latency_ms, 2) if self.min_latency_ms != float('inf') else None,
            "update_frequency_hz": round(self.update_frequency_hz, 3),
            "last_update": self.last_update,
            "missed_updates": self.missed_updates,
            "total_updates": self.total_updates,
            "latency_class": self.latency_class.value,
            "is_healthy": self.is_healthy,
            "estimated_alpha_decay_per_second": round(self.estimated_alpha_decay_per_second, 6),
        }


class AlphaDecayModel:
    """
    Models how trading alpha decays with information latency.
    
    Alpha decay is typically exponential:
    alpha(t) = alpha_0 * exp(-lambda * t)
    
    where lambda depends on:
    - Market efficiency
    - Competition
    - Information type
    """
    
    # Decay rates by information type (per second)
    DECAY_RATES = {
        InformationSource.EXCHANGE_PRICE: 0.5,      # Very fast decay
        InformationSource.EXCHANGE_ORDERBOOK: 0.8,  # Extremely fast
        InformationSource.ORACLE_CHAINLINK: 0.1,    # Slower (block times)
        InformationSource.ORACLE_PYTH: 0.2,         # Moderate
        InformationSource.ORACLE_UMA: 0.05,         # Slow (dispute period)
        InformationSource.NEWS_FEED: 0.02,          # News has longer half-life
        InformationSource.SOCIAL_TWITTER: 0.05,     # Social signals decay
        InformationSource.SOCIAL_REDDIT: 0.01,      # Reddit slower
        InformationSource.ON_CHAIN: 0.1,            # On-chain moderate
        InformationSource.PREDICTION_MARKET: 0.03,  # Prediction markets slower
    }
    
    def __init__(self):
        # Adaptive decay rates (learned from outcomes)
        self._adaptive_rates: Dict[InformationSource, float] = dict(self.DECAY_RATES)
        self._outcome_history: Dict[InformationSource, List[Tuple[float, float]]] = {
            s: [] for s in InformationSource
        }
        
        logger.info("Alpha decay model initialized")
    
    def calculate_remaining_alpha(
        self,
        source: InformationSource,
        latency_seconds: float,
        initial_alpha: float = 1.0,
    ) -> float:
        """
        Calculate remaining alpha after latency.
        
        Returns value between 0 and initial_alpha.
        """
        decay_rate = self._adaptive_rates.get(source, 0.1)
        remaining = initial_alpha * math.exp(-decay_rate * latency_seconds)
        return max(0.0, remaining)
    
    def calculate_effective_alpha(
        self,
        source: InformationSource,
        latency_ms: float,
        signal_strength: float,
    ) -> float:
        """
        Calculate effective alpha considering latency and signal strength.
        
        Returns effective alpha value.
        """
        latency_seconds = latency_ms / 1000.0
        remaining_alpha = self.calculate_remaining_alpha(source, latency_seconds)
        return remaining_alpha * signal_strength
    
    def record_outcome(
        self,
        source: InformationSource,
        latency_seconds: float,
        realized_alpha: float,
    ) -> None:
        """Record outcome for adaptive learning."""
        self._outcome_history[source].append((latency_seconds, realized_alpha))
        
        # Keep last 1000 outcomes per source
        if len(self._outcome_history[source]) > 1000:
            self._outcome_history[source] = self._outcome_history[source][-1000:]
        
        # Update adaptive rate if enough data
        if len(self._outcome_history[source]) >= 50:
            self._update_adaptive_rate(source)
    
    def _update_adaptive_rate(self, source: InformationSource) -> None:
        """Update adaptive decay rate from outcomes."""
        outcomes = self._outcome_history[source]
        
        # Fit exponential decay to outcomes
        latencies = np.array([o[0] for o in outcomes])
        alphas = np.array([o[1] for o in outcomes])
        
        # Filter valid data
        valid = (alphas > 0) & (latencies > 0)
        if valid.sum() < 10:
            return
        
        latencies = latencies[valid]
        alphas = alphas[valid]
        
        # Log-linear regression to estimate decay rate
        log_alphas = np.log(alphas + 1e-10)
        
        # Simple linear regression
        n = len(latencies)
        sum_x = latencies.sum()
        sum_y = log_alphas.sum()
        sum_xy = (latencies * log_alphas).sum()
        sum_x2 = (latencies ** 2).sum()
        
        denom = n * sum_x2 - sum_x ** 2
        if abs(denom) < 1e-10:
            return
        
        slope = (n * sum_xy - sum_x * sum_y) / denom
        
        # Decay rate is negative of slope
        estimated_rate = max(0.001, -slope)
        
        # Blend with prior
        old_rate = self._adaptive_rates[source]
        self._adaptive_rates[source] = 0.8 * old_rate + 0.2 * estimated_rate
    
    def get_decay_rate(self, source: InformationSource) -> float:
        """Get current decay rate for source."""
        return self._adaptive_rates.get(source, 0.1)
    
    def get_half_life_seconds(self, source: InformationSource) -> float:
        """Get half-life of alpha for source."""
        rate = self.get_decay_rate(source)
        if rate <= 0:
            return float('inf')
        return math.log(2) / rate


class InformationLatencyTracker:
    """
    Main information latency tracking system.
    
    Tracks latency for all information sources and
    calculates effective alpha considering delays.
    """
    
    def __init__(self):
        # Per-source tracking
        self._measurements: Dict[InformationSource, deque] = {
            s: deque(maxlen=1000) for s in InformationSource
        }
        self._profiles: Dict[InformationSource, SourceLatencyProfile] = {
            s: SourceLatencyProfile(source=s) for s in InformationSource
        }
        
        # Alpha decay model
        self.alpha_model = AlphaDecayModel()
        
        # Expected update intervals (seconds)
        self._expected_intervals: Dict[InformationSource, float] = {
            InformationSource.EXCHANGE_PRICE: 0.1,
            InformationSource.EXCHANGE_ORDERBOOK: 0.1,
            InformationSource.ORACLE_CHAINLINK: 60.0,
            InformationSource.ORACLE_PYTH: 1.0,
            InformationSource.ORACLE_UMA: 3600.0,
            InformationSource.NEWS_FEED: 60.0,
            InformationSource.SOCIAL_TWITTER: 10.0,
            InformationSource.SOCIAL_REDDIT: 60.0,
            InformationSource.ON_CHAIN: 12.0,
            InformationSource.PREDICTION_MARKET: 60.0,
        }
        
        # Latency thresholds (ms)
        self._latency_thresholds = {
            LatencyClass.REALTIME: 100,
            LatencyClass.FAST: 1000,
            LatencyClass.MODERATE: 10000,
            LatencyClass.SLOW: 60000,
            LatencyClass.STALE: float('inf'),
        }
        
        logger.info("Information latency tracker initialized")
    
    def record_measurement(
        self,
        source: InformationSource,
        data_timestamp: float,
        receipt_timestamp: Optional[float] = None,
        processing_delay_ms: float = 0.0,
    ) -> LatencyMeasurement:
        """
        Record a latency measurement.
        
        data_timestamp: When the data was generated at source
        receipt_timestamp: When MERID received the data (default: now)
        processing_delay_ms: Additional processing time
        """
        now = time.time()
        receipt = receipt_timestamp or now
        
        propagation_delay_ms = (receipt - data_timestamp) * 1000
        total_latency_ms = propagation_delay_ms + processing_delay_ms
        
        measurement = LatencyMeasurement(
            source=source,
            measured_latency_ms=total_latency_ms,
            timestamp=now,
            data_timestamp=data_timestamp,
            propagation_delay_ms=propagation_delay_ms,
            processing_delay_ms=processing_delay_ms,
        )
        
        self._measurements[source].append(measurement)
        self._update_profile(source)
        
        return measurement
    
    def _update_profile(self, source: InformationSource) -> None:
        """Update latency profile for source."""
        measurements = list(self._measurements[source])
        if not measurements:
            return
        
        profile = self._profiles[source]
        latencies = [m.total_latency_ms() for m in measurements]
        
        # Statistics
        profile.avg_latency_ms = float(np.mean(latencies))
        profile.p50_latency_ms = float(np.percentile(latencies, 50))
        profile.p95_latency_ms = float(np.percentile(latencies, 95))
        profile.p99_latency_ms = float(np.percentile(latencies, 99))
        profile.max_latency_ms = float(np.max(latencies))
        profile.min_latency_ms = float(np.min(latencies))
        
        # Update frequency
        if len(measurements) >= 2:
            timestamps = [m.timestamp for m in measurements]
            intervals = np.diff(timestamps)
            if len(intervals) > 0 and np.mean(intervals) > 0:
                profile.update_frequency_hz = 1.0 / np.mean(intervals)
        
        profile.last_update = measurements[-1].timestamp
        profile.total_updates = len(measurements)
        
        # Check for missed updates
        expected_interval = self._expected_intervals.get(source, 60.0)
        if len(measurements) >= 2:
            timestamps = [m.timestamp for m in measurements]
            intervals = np.diff(timestamps)
            missed = sum(1 for i in intervals if i > expected_interval * 2)
            profile.missed_updates = missed
        
        # Classify latency
        avg_ms = profile.avg_latency_ms
        if avg_ms < self._latency_thresholds[LatencyClass.REALTIME]:
            profile.latency_class = LatencyClass.REALTIME
        elif avg_ms < self._latency_thresholds[LatencyClass.FAST]:
            profile.latency_class = LatencyClass.FAST
        elif avg_ms < self._latency_thresholds[LatencyClass.MODERATE]:
            profile.latency_class = LatencyClass.MODERATE
        elif avg_ms < self._latency_thresholds[LatencyClass.SLOW]:
            profile.latency_class = LatencyClass.SLOW
        else:
            profile.latency_class = LatencyClass.STALE
        
        # Health check
        time_since_update = time.time() - profile.last_update
        max_gap = expected_interval * 3
        profile.is_healthy = (
            time_since_update < max_gap
            and profile.latency_class != LatencyClass.STALE
            and profile.missed_updates < profile.total_updates * 0.1
        )
        
        # Alpha decay rate
        profile.estimated_alpha_decay_per_second = self.alpha_model.get_decay_rate(source)
    
    def get_profile(self, source: InformationSource) -> SourceLatencyProfile:
        """Get latency profile for source."""
        return self._profiles[source]
    
    def get_all_profiles(self) -> Dict[InformationSource, SourceLatencyProfile]:
        """Get all latency profiles."""
        return self._profiles.copy()
    
    def get_effective_alpha(
        self,
        source: InformationSource,
        signal_strength: float = 1.0,
    ) -> float:
        """
        Get effective alpha for source considering current latency.
        
        Returns value between 0 and signal_strength.
        """
        profile = self._profiles[source]
        latency_ms = profile.avg_latency_ms
        
        return self.alpha_model.calculate_effective_alpha(
            source, latency_ms, signal_strength
        )
    
    def get_stale_sources(self) -> List[InformationSource]:
        """Get list of stale or unhealthy sources."""
        stale = []
        for source, profile in self._profiles.items():
            if not profile.is_healthy or profile.latency_class in (LatencyClass.STALE, LatencyClass.DEAD):
                stale.append(source)
        return stale
    
    def get_fastest_source(self, source_types: Optional[List[InformationSource]] = None) -> Optional[InformationSource]:
        """Get fastest healthy source from given types."""
        candidates = source_types or list(InformationSource)
        
        healthy = [
            (s, self._profiles[s].avg_latency_ms)
            for s in candidates
            if self._profiles[s].is_healthy
        ]
        
        if not healthy:
            return None
        
        return min(healthy, key=lambda x: x[1])[0]
    
    def should_use_source(self, source: InformationSource) -> Tuple[bool, str]:
        """
        Check if source should be used for trading decisions.
        
        Returns (should_use, reason).
        """
        profile = self._profiles[source]
        
        if not profile.is_healthy:
            return False, f"Source unhealthy (last update: {time.time() - profile.last_update:.1f}s ago)"
        
        if profile.latency_class == LatencyClass.STALE:
            return False, f"Source stale (avg latency: {profile.avg_latency_ms:.0f}ms)"
        
        # Check alpha decay
        effective_alpha = self.get_effective_alpha(source)
        if effective_alpha < 0.1:
            return False, f"Alpha decayed too much (effective: {effective_alpha:.2f})"
        
        return True, "Source acceptable"
    
    def get_latency_budget(self, source: InformationSource) -> float:
        """
        Get remaining latency budget before alpha decays below threshold.
        
        Returns milliseconds of acceptable additional latency.
        """
        threshold_alpha = 0.1
        decay_rate = self.alpha_model.get_decay_rate(source)
        
        if decay_rate <= 0:
            return float('inf')
        
        # Time until alpha = threshold
        max_time_seconds = -math.log(threshold_alpha) / decay_rate
        
        # Subtract current latency
        current_latency_seconds = self._profiles[source].avg_latency_ms / 1000
        remaining_seconds = max_time_seconds - current_latency_seconds
        
        return max(0, remaining_seconds * 1000)
    
    def get_status(self) -> Dict[str, Any]:
        """Get tracker status."""
        profiles = self._profiles
        healthy_count = sum(1 for p in profiles.values() if p.is_healthy)
        stale_sources = self.get_stale_sources()
        
        return {
            "total_sources": len(profiles),
            "healthy_sources": healthy_count,
            "stale_sources": [s.value for s in stale_sources],
            "profiles": {s.value: p.to_dict() for s, p in profiles.items()},
        }
    
    def get_summary(self) -> Dict[str, Any]:
        """Get summary of latency status."""
        profiles = self._profiles
        
        by_class = {c.value: 0 for c in LatencyClass}
        for p in profiles.values():
            by_class[p.latency_class.value] += 1
        
        avg_latencies = {
            s.value: round(p.avg_latency_ms, 2)
            for s, p in profiles.items()
            if p.total_updates > 0
        }
        
        return {
            "by_latency_class": by_class,
            "avg_latencies_ms": avg_latencies,
            "fastest_source": self.get_fastest_source().value if self.get_fastest_source() else None,
            "stale_count": len(self.get_stale_sources()),
        }


# Singleton instance
_latency_tracker: Optional[InformationLatencyTracker] = None


def get_latency_tracker() -> InformationLatencyTracker:
    """Get the singleton information latency tracker."""
    global _latency_tracker
    if _latency_tracker is None:
        _latency_tracker = InformationLatencyTracker()
    return _latency_tracker
