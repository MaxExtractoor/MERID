"""
MERID-OPS Data Provenance Scoring

Tracks the trustworthiness of data sources over time.
Sources decay in trust if they:
- Provide stale data
- Have high error rates
- Contradict verified outcomes
- Go offline frequently
"""

from __future__ import annotations

import threading
import hashlib
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set

from utils.logger import get_logger

logger = get_logger("ops.data_provenance")


class SourceType(Enum):
    """Types of data sources."""
    EXCHANGE = "exchange"
    NEWS_FEED = "news_feed"
    PREDICTION_MARKET = "prediction_market"
    ORACLE = "oracle"
    SOCIAL = "social"
    ON_CHAIN = "on_chain"
    INTERNAL = "internal"


@dataclass
class DataSource:
    """A tracked data source."""
    source_id: str
    source_type: SourceType
    name: str
    url: Optional[str] = None
    
    # Trust metrics
    base_trust: float = 0.7
    current_trust: float = 0.7
    trust_floor: float = 0.1
    trust_ceiling: float = 1.0
    
    # Performance tracking
    total_requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    stale_responses: int = 0
    contradictions: int = 0
    
    # Timing
    last_success: float = 0.0
    last_failure: float = 0.0
    avg_latency_ms: float = 0.0
    
    # Decay
    decay_rate_per_day: float = 0.02  # 2% daily decay without positive signals
    last_trust_update: float = field(default_factory=time.time)
    
    def record_success(self, latency_ms: float) -> None:
        """Record a successful request."""
        self.total_requests += 1
        self.successful_requests += 1
        self.last_success = time.time()
        
        # Update rolling average latency
        if self.avg_latency_ms == 0:
            self.avg_latency_ms = latency_ms
        else:
            self.avg_latency_ms = 0.9 * self.avg_latency_ms + 0.1 * latency_ms
        
        # Boost trust slightly
        self._adjust_trust(0.01)
    
    def record_failure(self, reason: str) -> None:
        """Record a failed request."""
        self.total_requests += 1
        self.failed_requests += 1
        self.last_failure = time.time()
        
        # Penalize trust
        self._adjust_trust(-0.05)
        
        logger.warning("Source %s failed: %s", self.source_id, reason)
    
    def record_stale(self) -> None:
        """Record a stale response."""
        self.stale_responses += 1
        self._adjust_trust(-0.02)
    
    def record_contradiction(self, details: str) -> None:
        """Record a contradiction with verified data."""
        self.contradictions += 1
        self._adjust_trust(-0.1)
        
        logger.warning("Source %s contradiction: %s", self.source_id, details)
    
    def _adjust_trust(self, delta: float) -> None:
        """Adjust trust score within bounds."""
        self.current_trust = max(
            self.trust_floor,
            min(self.trust_ceiling, self.current_trust + delta)
        )
        self.last_trust_update = time.time()
    
    def apply_decay(self) -> float:
        """Apply time-based trust decay."""
        days_since_update = (time.time() - self.last_trust_update) / 86400
        decay = self.decay_rate_per_day * days_since_update
        
        if decay > 0:
            self._adjust_trust(-decay)
        
        return self.current_trust
    
    def get_success_rate(self) -> float:
        """Get success rate."""
        if self.total_requests == 0:
            return 1.0
        return self.successful_requests / self.total_requests
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "source_id": self.source_id,
            "source_type": self.source_type.value,
            "name": self.name,
            "url": self.url,
            "current_trust": round(self.current_trust, 3),
            "base_trust": self.base_trust,
            "success_rate": round(self.get_success_rate(), 3),
            "total_requests": self.total_requests,
            "failed_requests": self.failed_requests,
            "stale_responses": self.stale_responses,
            "contradictions": self.contradictions,
            "avg_latency_ms": round(self.avg_latency_ms, 1),
            "last_success": self.last_success,
            "last_failure": self.last_failure,
        }


@dataclass
class DataPoint:
    """A piece of data with provenance."""
    data_id: str
    source_id: str
    data_type: str
    value: Any
    timestamp: float
    provenance_chain: List[str] = field(default_factory=list)
    trust_score: float = 0.0
    verified: bool = False
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "data_id": self.data_id,
            "source_id": self.source_id,
            "data_type": self.data_type,
            "value": self.value,
            "timestamp": self.timestamp,
            "provenance_chain": self.provenance_chain,
            "trust_score": self.trust_score,
            "verified": self.verified,
        }


class DataProvenanceTracker:
    """
    Tracks data provenance and source trustworthiness.
    
    Responsibilities:
    - Register and track data sources
    - Score data based on source trust
    - Detect stale or contradictory data
    - Maintain provenance chains
    """
    
    def __init__(self):
        self._sources: Dict[str, DataSource] = {}
        self._data_points: Dict[str, DataPoint] = {}
        self._max_data_points = 10000
        
        # Initialize default sources
        self._init_default_sources()
        
        logger.info("Data provenance tracker initialized with %d sources", len(self._sources))
    
    def _init_default_sources(self) -> None:
        """Initialize default data sources."""
        defaults = [
            ("coinbase", SourceType.EXCHANGE, "Coinbase", 0.85),
            ("binance", SourceType.EXCHANGE, "Binance", 0.80),
            ("kraken", SourceType.EXCHANGE, "Kraken", 0.82),
            ("coindesk", SourceType.NEWS_FEED, "CoinDesk", 0.70),
            ("cointelegraph", SourceType.NEWS_FEED, "CoinTelegraph", 0.65),
            ("polymarket", SourceType.PREDICTION_MARKET, "Polymarket", 0.75),
            ("kalshi", SourceType.PREDICTION_MARKET, "Kalshi", 0.78),
            ("chainlink", SourceType.ORACLE, "Chainlink", 0.90),
            ("pyth", SourceType.ORACLE, "Pyth Network", 0.85),
            ("twitter", SourceType.SOCIAL, "Twitter/X", 0.40),
            ("etherscan", SourceType.ON_CHAIN, "Etherscan", 0.95),
        ]
        
        for source_id, source_type, name, base_trust in defaults:
            self._sources[source_id] = DataSource(
                source_id=source_id,
                source_type=source_type,
                name=name,
                base_trust=base_trust,
                current_trust=base_trust,
            )
    
    def register_source(
        self,
        source_id: str,
        source_type: SourceType,
        name: str,
        base_trust: float = 0.5,
        url: Optional[str] = None,
    ) -> DataSource:
        """Register a new data source."""
        source = DataSource(
            source_id=source_id,
            source_type=source_type,
            name=name,
            url=url,
            base_trust=base_trust,
            current_trust=base_trust,
        )
        self._sources[source_id] = source
        
        logger.info("Registered source: %s (%s)", source_id, source_type.value)
        return source
    
    def get_source(self, source_id: str) -> Optional[DataSource]:
        """Get a source by ID."""
        return self._sources.get(source_id)
    
    def record_data(
        self,
        source_id: str,
        data_type: str,
        value: Any,
        latency_ms: float = 0.0,
        provenance_chain: Optional[List[str]] = None,
    ) -> Optional[DataPoint]:
        """Record a data point from a source."""
        source = self._sources.get(source_id)
        if not source:
            logger.warning("Unknown source: %s", source_id)
            return None
        
        # Record success
        source.record_success(latency_ms)
        
        # Create data point
        data_id = f"dp_{source_id}_{int(time.time() * 1000)}"
        chain = provenance_chain or []
        chain.append(source_id)
        
        data_point = DataPoint(
            data_id=data_id,
            source_id=source_id,
            data_type=data_type,
            value=value,
            timestamp=time.time(),
            provenance_chain=chain,
            trust_score=source.current_trust,
        )
        
        # Store with cleanup
        self._data_points[data_id] = data_point
        if len(self._data_points) > self._max_data_points:
            # Remove oldest
            oldest = min(self._data_points.values(), key=lambda x: x.timestamp)
            del self._data_points[oldest.data_id]
        
        return data_point
    
    def record_failure(self, source_id: str, reason: str) -> None:
        """Record a source failure."""
        source = self._sources.get(source_id)
        if source:
            source.record_failure(reason)
    
    def record_contradiction(
        self,
        source_id: str,
        data_point_id: str,
        verified_value: Any,
        details: str,
    ) -> None:
        """Record that a source contradicted verified data."""
        source = self._sources.get(source_id)
        if source:
            source.record_contradiction(details)
        
        # Mark data point as unverified
        if data_point_id in self._data_points:
            self._data_points[data_point_id].verified = False
    
    def verify_data_point(self, data_point_id: str) -> bool:
        """Mark a data point as verified."""
        if data_point_id in self._data_points:
            self._data_points[data_point_id].verified = True
            return True
        return False
    
    def get_trust_weighted_value(
        self,
        data_type: str,
        max_age_seconds: float = 60,
    ) -> Optional[tuple[Any, float]]:
        """
        Get trust-weighted consensus value for a data type.
        
        Returns (value, confidence) or None.
        """
        cutoff = time.time() - max_age_seconds
        
        # Get recent data points of this type
        recent = [
            dp for dp in self._data_points.values()
            if dp.data_type == data_type and dp.timestamp > cutoff
        ]
        
        if not recent:
            return None
        
        # Weight by trust score
        total_trust = sum(dp.trust_score for dp in recent)
        if total_trust == 0:
            return None
        
        # For numeric values, compute weighted average
        if all(isinstance(dp.value, (int, float)) for dp in recent):
            weighted_sum = sum(dp.value * dp.trust_score for dp in recent)
            return weighted_sum / total_trust, total_trust / len(recent)
        
        # For non-numeric, return highest trust value
        best = max(recent, key=lambda x: x.trust_score)
        return best.value, best.trust_score
    
    def apply_all_decay(self) -> int:
        """Apply decay to all sources."""
        count = 0
        for source in self._sources.values():
            old_trust = source.current_trust
            source.apply_decay()
            if source.current_trust < old_trust:
                count += 1
        return count
    
    def get_sources_by_type(self, source_type: SourceType) -> List[DataSource]:
        """Get all sources of a type."""
        return [s for s in self._sources.values() if s.source_type == source_type]
    
    def get_low_trust_sources(self, threshold: float = 0.5) -> List[DataSource]:
        """Get sources below trust threshold."""
        return [s for s in self._sources.values() if s.current_trust < threshold]
    
    def get_status(self) -> Dict[str, Any]:
        """Get tracker status."""
        sources = list(self._sources.values())
        
        return {
            "total_sources": len(sources),
            "avg_trust": sum(s.current_trust for s in sources) / len(sources) if sources else 0,
            "low_trust_count": len(self.get_low_trust_sources()),
            "total_data_points": len(self._data_points),
            "verified_data_points": sum(1 for dp in self._data_points.values() if dp.verified),
            "sources_by_type": {
                st.value: len(self.get_sources_by_type(st))
                for st in SourceType
            },
        }
    
    def get_all_sources(self) -> List[Dict[str, Any]]:
        """Get all sources."""
        return [s.to_dict() for s in self._sources.values()]


# Singleton
_provenance_tracker: Optional[DataProvenanceTracker] = None
_provenance_tracker_lock = threading.Lock()


def get_provenance_tracker() -> DataProvenanceTracker:
    """Get the singleton provenance tracker."""
    global _provenance_tracker
    if _provenance_tracker is None:
        with _provenance_tracker_lock:
            if _provenance_tracker is None:
                _provenance_tracker = DataProvenanceTracker()
    return _provenance_tracker
