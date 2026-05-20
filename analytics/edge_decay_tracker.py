"""Edge Decay Tracking with Exponential Moving Average.

Tracks the erosion of trading edge over time using exponential moving averages
of realized edge. Helps identify when strategies are losing effectiveness due to
market conditions, competition, or alpha decay.

Key Features:
- Exponential moving average of realized edge
- Edge decay detection and alerting
- Historical edge tracking by strategy and asset
- Decay rate calculation
- Edge recovery monitoring

Usage:
    from analytics.edge_decay_tracker import get_edge_decay_tracker
    
    tracker = get_edge_decay_tracker()
    
    # Record realized edge from a trade
    tracker.record_edge(
        strategy="momentum",
        asset="BTC",
        expected_edge=0.05,
        realized_edge=0.03,
        timestamp=datetime.now()
    )
    
    # Get current edge estimate
    current_edge = tracker.get_current_edge(strategy="momentum", asset="BTC")
    
    # Check if edge is decaying
    decay_status = tracker.check_decay_status(strategy="momentum", asset="BTC")
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple
import math

from utils.logger import get_logger

logger = get_logger("analytics.edge_decay_tracker")


class EdgeStatus(str, Enum):
    """Edge status classification."""
    STRONG = "strong"           # Edge is strong and stable
    STABLE = "stable"           # Edge is stable
    DECAYING = "decaying"       # Edge is showing signs of decay
    WEAK = "weak"              # Edge is weak
    CRITICAL = "critical"       # Edge is critically low


@dataclass
class EdgeObservation:
    """A single edge observation."""
    strategy: str
    asset: str
    expected_edge: float
    realized_edge: float
    timestamp: datetime
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class EdgeMetrics:
    """Edge metrics for a strategy-asset pair."""
    strategy: str
    asset: str
    
    # Current edge estimates
    current_ema_edge: float
    current_sma_edge: float
    raw_mean_edge: float
    
    # Decay metrics
    decay_rate: float  # Rate of edge decay per day
    decay_status: EdgeStatus
    
    # Statistics
    observation_count: int
    last_observation: Optional[datetime]
    first_observation: Optional[datetime]
    
    # Volatility
    edge_volatility: float
    edge_std: float
    
    # Confidence
    confidence_score: float  # 0-1 based on sample size and consistency


@dataclass
class DecayAlert:
    """Alert generated when edge decay is detected."""
    strategy: str
    asset: str
    alert_type: EdgeStatus
    current_edge: float
    threshold_edge: float
    decay_rate: float
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    message: str = ""


@dataclass
class EdgeDecayConfig:
    """Edge decay tracking configuration."""
    ema_span: int = 20  # EMA span for edge smoothing
    sma_span: int = 50  # SMA span for comparison
    min_observations: int = 10  # Minimum observations before calculating metrics
    decay_threshold: float = 0.3  # Threshold for decay detection (30% drop)
    critical_threshold: float = 0.5  # Critical threshold (50% drop)
    volatility_window: int = 20  # Window for volatility calculation
    alert_enabled: bool = True  # Enable decay alerts


class EdgeDecayTracker:
    """Edge decay tracker using exponential moving averages.
    
    Tracks the erosion of trading edge over time and alerts when
    strategies are losing effectiveness.
    """
    
    _instance: Optional["EdgeDecayTracker"] = None
    _lock = threading.Lock()
    
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialize()
        return cls._instance
    
    def _initialize(self):
        """Initialize the edge decay tracker."""
        self._config = EdgeDecayConfig()
        self._observations: List[EdgeObservation] = []
        self._observations_lock = threading.Lock()
        self._alerts: List[DecayAlert] = []
        self._alerts_lock = threading.Lock()
        
        # Cache for edge metrics
        self._metrics_cache: Dict[Tuple[str, str], EdgeMetrics] = {}
        self._cache_lock = threading.Lock()
        self._cache_ttl_seconds = 60
        self._cache_timestamp: Optional[datetime] = None
        
        logger.info("EdgeDecayTracker initialized")
    
    def get_config(self) -> EdgeDecayConfig:
        """Get the edge decay configuration."""
        return self._config
    
    def set_config(self, config: EdgeDecayConfig):
        """Update the edge decay configuration."""
        self._config = config
        logger.info("Edge decay configuration updated")
    
    def record_edge(
        self,
        strategy: str,
        asset: str,
        expected_edge: float,
        realized_edge: float,
        timestamp: Optional[datetime] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> None:
        """Record an edge observation.
        
        Args:
            strategy: Strategy name
            asset: Asset ticker
            expected_edge: Expected edge from the strategy
            realized_edge: Realized edge from execution
            timestamp: Observation timestamp (uses current time if None)
            metadata: Additional metadata
        """
        if timestamp is None:
            timestamp = datetime.now(timezone.utc)
        
        observation = EdgeObservation(
            strategy=strategy,
            asset=asset,
            expected_edge=expected_edge,
            realized_edge=realized_edge,
            timestamp=timestamp,
            metadata=metadata or {}
        )
        
        with self._observations_lock:
            self._observations.append(observation)
            # Keep last 1000 observations per strategy-asset pair
            self._prune_observations()
        
        # Invalidate cache
        with self._cache_lock:
            self._cache_timestamp = None
        
        logger.debug(
            f"Edge recorded: strategy={strategy} asset={asset} "
            f"expected={expected_edge:.3f} realized={realized_edge:.3f}"
        )
    
    def _prune_observations(self):
        """Prune old observations to keep memory usage manageable."""
        # Group by strategy-asset pair
        pairs = {}
        for obs in self._observations:
            key = (obs.strategy, obs.asset)
            if key not in pairs:
                pairs[key] = []
            pairs[key].append(obs)
        
        # Keep last 1000 observations per pair
        pruned_observations = []
        for key, obs_list in pairs.items():
            # Sort by timestamp and keep last 1000
            obs_list.sort(key=lambda x: x.timestamp)
            pruned_observations.extend(obs_list[-1000:])
        
        self._observations = pruned_observations
    
    def get_current_edge(
        self,
        strategy: str,
        asset: str,
        use_ema: bool = True
    ) -> Optional[float]:
        """Get current edge estimate for a strategy-asset pair.
        
        Args:
            strategy: Strategy name
            asset: Asset ticker
            use_ema: Use EMA if True, SMA if False
            
        Returns:
            Current edge estimate or None if insufficient data
        """
        metrics = self.get_edge_metrics(strategy, asset)
        if metrics is None:
            return None
        
        return metrics.current_ema_edge if use_ema else metrics.current_sma_edge
    
    def get_edge_metrics(self, strategy: str, asset: str) -> Optional[EdgeMetrics]:
        """Get comprehensive edge metrics for a strategy-asset pair.
        
        Args:
            strategy: Strategy name
            asset: Asset ticker
            
        Returns:
            EdgeMetrics or None if insufficient data
        """
        # Check cache
        with self._cache_lock:
            if self._cache_timestamp:
                cache_age = (datetime.now(timezone.utc) - self._cache_timestamp).total_seconds()
                if cache_age < self._cache_ttl_seconds:
                    key = (strategy, asset)
                    if key in self._metrics_cache:
                        return self._metrics_cache[key]
        
        # Get observations for this pair
        with self._observations_lock:
            observations = [
                obs for obs in self._observations
                if obs.strategy == strategy and obs.asset == asset
            ]
        
        if len(observations) < self._config.min_observations:
            return None
        
        # Sort by timestamp
        observations.sort(key=lambda x: x.timestamp)
        
        # Calculate metrics
        realized_edges = [obs.realized_edge for obs in observations]
        
        # Calculate EMA
        ema_edge = self._calculate_ema(realized_edges, self._config.ema_span)
        
        # Calculate SMA
        sma_edge = self._calculate_sma(realized_edges, self._config.sma_span)
        
        # Calculate raw mean
        raw_mean = sum(realized_edges) / len(realized_edges)
        
        # Calculate decay rate
        decay_rate = self._calculate_decay_rate(realized_edges, observations)
        
        # Determine decay status
        decay_status = self._determine_decay_status(ema_edge, sma_edge, decay_rate)
        
        # Calculate volatility
        edge_volatility, edge_std = self._calculate_volatility(realized_edges)
        
        # Calculate confidence score
        confidence_score = self._calculate_confidence_score(len(observations), edge_volatility)
        
        # Get timestamps
        first_obs = observations[0].timestamp
        last_obs = observations[-1].timestamp
        
        metrics = EdgeMetrics(
            strategy=strategy,
            asset=asset,
            current_ema_edge=ema_edge,
            current_sma_edge=sma_edge,
            raw_mean_edge=raw_mean,
            decay_rate=decay_rate,
            decay_status=decay_status,
            observation_count=len(observations),
            last_observation=last_obs,
            first_observation=first_obs,
            edge_volatility=edge_volatility,
            edge_std=edge_std,
            confidence_score=confidence_score
        )
        
        # Update cache
        with self._cache_lock:
            self._metrics_cache[(strategy, asset)] = metrics
            self._cache_timestamp = datetime.now(timezone.utc)
        
        # Check for decay alerts
        if self._config.alert_enabled:
            self._check_decay_alert(metrics)
        
        return metrics
    
    def _calculate_ema(self, values: List[float], span: int) -> float:
        """Calculate exponential moving average.
        
        Args:
            values: List of values
            span: EMA span
            
        Returns:
            EMA value
        """
        if not values:
            return 0.0
        
        alpha = 2 / (span + 1)
        ema = values[0]
        
        for value in values[1:]:
            ema = alpha * value + (1 - alpha) * ema
        
        return ema
    
    def _calculate_sma(self, values: List[float], span: int) -> float:
        """Calculate simple moving average.
        
        Args:
            values: List of values
            span: SMA span
            
        Returns:
            SMA value
        """
        if not values:
            return 0.0
        
        # Use last `span` values
        window = values[-span:]
        return sum(window) / len(window)
    
    def _calculate_decay_rate(
        self,
        values: List[float],
        observations: List[EdgeObservation]
    ) -> float:
        """Calculate edge decay rate per day.
        
        Args:
            values: Edge values
            observations: Edge observations with timestamps
            
        Returns:
            Decay rate per day (negative if decaying)
        """
        if len(observations) < 2:
            return 0.0
        
        # Calculate linear regression on edge vs time
        n = len(observations)
        if n < 2:
            return 0.0
        
        # Convert timestamps to days since first observation
        first_time = observations[0].timestamp
        times = [(obs.timestamp - first_time).total_seconds() / 86400 for obs in observations]
        
        # Calculate linear regression
        sum_x = sum(times)
        sum_y = sum(values)
        sum_xy = sum(t * v for t, v in zip(times, values))
        sum_x2 = sum(t * t for t in times)
        
        if n * sum_x2 - sum_x * sum_x == 0:
            return 0.0
        
        slope = (n * sum_xy - sum_x * sum_y) / (n * sum_x2 - sum_x * sum_x)
        
        return slope  # Decay rate per day
    
    def _determine_decay_status(
        self,
        ema_edge: float,
        sma_edge: float,
        decay_rate: float
    ) -> EdgeStatus:
        """Determine edge decay status.
        
        Args:
            ema_edge: Current EMA edge
            sma_edge: Current SMA edge
            decay_rate: Decay rate per day
            
        Returns:
            EdgeStatus
        """
        # Calculate relative drop from SMA to EMA
        if sma_edge != 0:
            relative_drop = (sma_edge - ema_edge) / abs(sma_edge)
        else:
            relative_drop = 0
        
        # Determine status based on drop and decay rate
        if relative_drop >= self._config.critical_threshold or decay_rate < -0.1:
            return EdgeStatus.CRITICAL
        elif relative_drop >= self._config.decay_threshold or decay_rate < -0.05:
            return EdgeStatus.DECAYING
        elif abs(decay_rate) < 0.01 and relative_drop < 0.1:
            return EdgeStatus.STRONG
        elif ema_edge > 0:
            return EdgeStatus.STABLE
        else:
            return EdgeStatus.WEAK
    
    def _calculate_volatility(self, values: List[float]) -> Tuple[float, float]:
        """Calculate edge volatility and standard deviation.
        
        Args:
            values: Edge values
            
        Returns:
            Tuple of (volatility, std)
        """
        if len(values) < 2:
            return 0.0, 0.0
        
        mean = sum(values) / len(values)
        variance = sum((v - mean) ** 2 for v in values) / (len(values) - 1)
        std = math.sqrt(variance)
        
        # Volatility as coefficient of variation
        volatility = std / abs(mean) if mean != 0 else 0
        
        return volatility, std
    
    def _calculate_confidence_score(self, n_observations: int, volatility: float) -> float:
        """Calculate confidence score based on sample size and volatility.
        
        Args:
            n_observations: Number of observations
            volatility: Edge volatility
            
        Returns:
            Confidence score (0-1)
        """
        # Sample size contribution (more observations = higher confidence)
        sample_score = min(n_observations / 100, 1.0)
        
        # Volatility contribution (lower volatility = higher confidence)
        volatility_score = max(0, 1 - volatility)
        
        # Combined score
        confidence = 0.6 * sample_score + 0.4 * volatility_score
        
        return confidence
    
    def _check_decay_alert(self, metrics: EdgeMetrics):
        """Check if decay alert should be generated.
        
        Args:
            metrics: Edge metrics
        """
        if metrics.decay_status in [EdgeStatus.DECAYING, EdgeStatus.CRITICAL]:
            alert = DecayAlert(
                strategy=metrics.strategy,
                asset=metrics.asset,
                alert_type=metrics.decay_status,
                current_edge=metrics.current_ema_edge,
                threshold_edge=metrics.current_sma_edge,
                decay_rate=metrics.decay_rate,
                message=(
                    f"Edge decay detected for {metrics.strategy}/{metrics.asset}: "
                    f"current={metrics.current_ema_edge:.3f} vs baseline={metrics.current_sma_edge:.3f}, "
                    f"decay_rate={metrics.decay_rate:.4f}/day"
                )
            )
            
            with self._alerts_lock:
                self._alerts.append(alert)
                # Keep last 100 alerts
                self._alerts = self._alerts[-100:]
            
            logger.warning(alert.message)
    
    def check_decay_status(self, strategy: str, asset: str) -> Optional[EdgeStatus]:
        """Check edge decay status for a strategy-asset pair.
        
        Args:
            strategy: Strategy name
            asset: Asset ticker
            
        Returns:
            EdgeStatus or None if insufficient data
        """
        metrics = self.get_edge_metrics(strategy, asset)
        if metrics is None:
            return None
        return metrics.decay_status
    
    def get_recent_alerts(self, limit: int = 10) -> List[DecayAlert]:
        """Get recent decay alerts.
        
        Args:
            limit: Maximum number of alerts to return
            
        Returns:
            List of recent alerts
        """
        with self._alerts_lock:
            return self._alerts[-limit:]
    
    def get_summary(self) -> Dict[str, Any]:
        """Get summary of edge decay tracking.
        
        Returns:
            Summary dictionary
        """
        with self._observations_lock:
            total_observations = len(self._observations)
            
            # Group by strategy-asset pairs
            pairs = {}
            for obs in self._observations:
                key = (obs.strategy, obs.asset)
                if key not in pairs:
                    pairs[key] = []
                pairs[key].append(obs)
        
        # Calculate metrics for each pair
        pair_summaries = {}
        for (strategy, asset), obs_list in pairs.items():
            metrics = self.get_edge_metrics(strategy, asset)
            if metrics:
                pair_summaries[f"{strategy}/{asset}"] = {
                    "current_edge": metrics.current_ema_edge,
                    "decay_status": metrics.decay_status.value,
                    "decay_rate": metrics.decay_rate,
                    "confidence": metrics.confidence_score,
                    "observations": metrics.observation_count
                }
        
        # Get recent alerts
        recent_alerts = self.get_recent_alerts(limit=5)
        
        return {
            "total_observations": total_observations,
            "tracked_pairs": len(pairs),
            "pair_summaries": pair_summaries,
            "recent_alerts": [
                {
                    "strategy": alert.strategy,
                    "asset": alert.asset,
                    "type": alert.alert_type.value,
                    "message": alert.message,
                    "timestamp": alert.timestamp.isoformat()
                }
                for alert in recent_alerts
            ]
        }


# Singleton accessor
_edge_decay_tracker: Optional[EdgeDecayTracker] = None
_edge_decay_tracker_lock = threading.Lock()


def get_edge_decay_tracker() -> EdgeDecayTracker:
    """Get the singleton EdgeDecayTracker instance."""
    global _edge_decay_tracker
    if _edge_decay_tracker is None:
        with _edge_decay_tracker_lock:
            if _edge_decay_tracker is None:
                _edge_decay_tracker = EdgeDecayTracker()
    return _edge_decay_tracker
