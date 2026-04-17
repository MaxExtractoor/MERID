"""
Feature Store for MERID
Centralized storage and serving of features for quant models and agents.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import numpy as np

from core.cache_manager import get_cache_manager
from core.persistence_manager import get_persistence_manager
from utils.logger import get_logger

logger = get_logger("core.feature_store")


class FeatureType(Enum):
    """Types of features."""
    MARKET = "market"
    ONCHAIN = "onchain"
    SOCIAL = "social"
    TECHNICAL = "technical"
    FUNDAMENTAL = "fundamental"
    DERIVED = "derived"


class ComputeMode(Enum):
    """Feature computation mode."""
    REALTIME = "realtime"
    BATCH = "batch"
    HYBRID = "hybrid"


@dataclass
class FeatureDefinition:
    """Definition of a feature."""
    name: str
    feature_type: FeatureType
    compute_mode: ComputeMode
    compute_func: Callable[[Dict[str, Any]], float]
    dependencies: List[str]
    ttl_seconds: float
    version: str
    description: str
    metadata: Dict[str, Any]


@dataclass
class FeatureValue:
    """A computed feature value."""
    feature_name: str
    timestamp: float
    value: float
    entity_id: str  # Symbol, address, etc.
    metadata: Dict[str, Any]


class FeatureRegistry:
    """Registry of feature definitions."""
    
    def __init__(self):
        self._features: Dict[str, FeatureDefinition] = {}
    
    def register(self, feature: FeatureDefinition) -> None:
        """Register a feature definition."""
        if feature.name in self._features:
            logger.warning(f"Feature {feature.name} already registered, replacing")
        
        self._features[feature.name] = feature
        logger.info(f"Registered feature: {feature.name} (type: {feature.feature_type.value})")
    
    def get(self, feature_name: str) -> Optional[FeatureDefinition]:
        """Get a feature definition."""
        return self._features.get(feature_name)
    
    def list_features(
        self,
        feature_type: Optional[FeatureType] = None
    ) -> List[FeatureDefinition]:
        """List all features, optionally filtered by type."""
        features = list(self._features.values())
        
        if feature_type:
            features = [f for f in features if f.feature_type == feature_type]
        
        return features
    
    def get_dependencies(self, feature_name: str) -> List[str]:
        """Get all dependencies for a feature."""
        feature = self._features.get(feature_name)
        if not feature:
            return []
        
        deps = set(feature.dependencies)
        
        # Recursively get dependencies
        for dep in feature.dependencies:
            deps.update(self.get_dependencies(dep))
        
        return list(deps)


class FeatureStore:
    """Centralized feature store."""
    
    def __init__(self, storage_dir: str = "data/features"):
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        
        self._registry = FeatureRegistry()
        self._cache = get_cache_manager().get_cache("features")
        self._persistence = get_persistence_manager()
        
        # In-memory feature values (recent window)
        self._feature_values: Dict[str, List[FeatureValue]] = {}
        self._max_history = 1000  # Keep last 1000 values per feature
    
    def register_feature(self, feature: FeatureDefinition) -> None:
        """Register a feature."""
        self._registry.register(feature)
    
    def compute_feature(
        self,
        feature_name: str,
        entity_id: str,
        context: Dict[str, Any],
        force_recompute: bool = False
    ) -> Optional[float]:
        """Compute a feature value."""
        feature = self._registry.get(feature_name)
        if not feature:
            logger.error(f"Feature {feature_name} not registered")
            return None
        
        # Check cache
        cache_key = f"{feature_name}:{entity_id}"
        if not force_recompute:
            cached_value = self._cache.get(cache_key)
            if cached_value is not None:
                return cached_value
        
        try:
            # Compute dependencies first
            dep_values = {}
            for dep_name in feature.dependencies:
                dep_value = self.compute_feature(dep_name, entity_id, context)
                if dep_value is None:
                    logger.warning(f"Dependency {dep_name} returned None for {feature_name}")
                dep_values[dep_name] = dep_value
            
            # Add dependencies to context
            context_with_deps = {**context, **dep_values}
            
            # Compute feature
            value = feature.compute_func(context_with_deps)
            
            # Store value
            feature_value = FeatureValue(
                feature_name=feature_name,
                timestamp=time.time(),
                value=value,
                entity_id=entity_id,
                metadata={"context_keys": list(context.keys())}
            )
            
            self._store_value(feature_value)
            
            # Cache value
            self._cache.set(cache_key, value, ttl=feature.ttl_seconds)
            
            return value
            
        except Exception as exc:
            logger.error(f"Failed to compute feature {feature_name}: {exc}")
            return None
    
    def compute_features(
        self,
        feature_names: List[str],
        entity_id: str,
        context: Dict[str, Any]
    ) -> Dict[str, float]:
        """Compute multiple features."""
        results = {}
        
        for feature_name in feature_names:
            value = self.compute_feature(feature_name, entity_id, context)
            if value is not None:
                results[feature_name] = value
        
        return results
    
    def get_feature_history(
        self,
        feature_name: str,
        entity_id: str,
        start_time: Optional[float] = None,
        end_time: Optional[float] = None,
        limit: int = 100
    ) -> List[FeatureValue]:
        """Get historical feature values."""
        if feature_name not in self._feature_values:
            return []
        
        values = self._feature_values[feature_name]
        
        # Filter by entity
        values = [v for v in values if v.entity_id == entity_id]
        
        # Filter by time
        if start_time:
            values = [v for v in values if v.timestamp >= start_time]
        if end_time:
            values = [v for v in values if v.timestamp <= end_time]
        
        return values[-limit:]
    
    def get_feature_vector(
        self,
        feature_names: List[str],
        entity_id: str,
        context: Dict[str, Any]
    ) -> np.ndarray:
        """Get a feature vector for ML models."""
        features = self.compute_features(feature_names, entity_id, context)
        
        # Maintain order
        vector = [features.get(name, 0.0) for name in feature_names]
        
        return np.array(vector)
    
    def _store_value(self, value: FeatureValue) -> None:
        """Store a feature value."""
        if value.feature_name not in self._feature_values:
            self._feature_values[value.feature_name] = []
        
        self._feature_values[value.feature_name].append(value)
        
        # Trim history
        if len(self._feature_values[value.feature_name]) > self._max_history:
            self._feature_values[value.feature_name] = \
                self._feature_values[value.feature_name][-self._max_history:]
    
    def persist_features(self) -> None:
        """Persist feature values to disk."""
        logger.info("Persisting feature values")
        
        data = {}
        for feature_name, values in self._feature_values.items():
            data[feature_name] = [
                {
                    "timestamp": v.timestamp,
                    "value": v.value,
                    "entity_id": v.entity_id,
                    "metadata": v.metadata
                }
                for v in values
            ]
        
        date_str = time.strftime("%Y-%m-%d")
        file_path = self.storage_dir / f"features_{date_str}.json"
        
        self._persistence.write_json(str(file_path), data, immediate=False)
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get feature store statistics."""
        return {
            "total_features": len(self._registry._features),
            "features_by_type": {
                ft.value: len([f for f in self._registry._features.values() if f.feature_type == ft])
                for ft in FeatureType
            },
            "total_values_stored": sum(len(v) for v in self._feature_values.values()),
            "features_with_values": len(self._feature_values),
            "cache_stats": self._cache.get_stats()
        }


# Predefined feature computation functions
def compute_volatility(context: Dict[str, Any]) -> float:
    """Compute volatility from price history."""
    prices = context.get("prices", [])
    if len(prices) < 2:
        return 0.0
    
    returns = np.diff(np.log(prices))
    return float(np.std(returns) * np.sqrt(252))  # Annualized


def compute_momentum(context: Dict[str, Any]) -> float:
    """Compute momentum from price history."""
    prices = context.get("prices", [])
    if len(prices) < 2:
        return 0.0
    
    return float((prices[-1] - prices[0]) / prices[0])


def compute_spread_bps(context: Dict[str, Any]) -> float:
    """Compute bid-ask spread in basis points."""
    bid = context.get("bid", 0.0)
    ask = context.get("ask", 0.0)
    
    if bid <= 0 or ask <= 0:
        return 0.0
    
    mid = (bid + ask) / 2
    spread = ask - bid
    
    return (spread / mid) * 10000


def compute_liquidity_score(context: Dict[str, Any]) -> float:
    """Compute liquidity score."""
    volume = context.get("volume_24h", 0.0)
    market_cap = context.get("market_cap", 1.0)
    
    if market_cap <= 0:
        return 0.0
    
    return min(volume / market_cap, 1.0)


def compute_social_sentiment(context: Dict[str, Any]) -> float:
    """Compute social sentiment score."""
    positive = context.get("positive_mentions", 0)
    negative = context.get("negative_mentions", 0)
    total = positive + negative
    
    if total == 0:
        return 0.5  # Neutral
    
    return positive / total


def register_default_features(store: FeatureStore) -> None:
    """Register default features."""
    
    # Market features
    store.register_feature(FeatureDefinition(
        name="volatility_30d",
        feature_type=FeatureType.MARKET,
        compute_mode=ComputeMode.BATCH,
        compute_func=compute_volatility,
        dependencies=[],
        ttl_seconds=3600.0,
        version="1.0",
        description="30-day annualized volatility",
        metadata={"window": 30}
    ))
    
    store.register_feature(FeatureDefinition(
        name="momentum_7d",
        feature_type=FeatureType.MARKET,
        compute_mode=ComputeMode.BATCH,
        compute_func=compute_momentum,
        dependencies=[],
        ttl_seconds=3600.0,
        version="1.0",
        description="7-day price momentum",
        metadata={"window": 7}
    ))
    
    store.register_feature(FeatureDefinition(
        name="spread_bps",
        feature_type=FeatureType.MARKET,
        compute_mode=ComputeMode.REALTIME,
        compute_func=compute_spread_bps,
        dependencies=[],
        ttl_seconds=60.0,
        version="1.0",
        description="Bid-ask spread in basis points",
        metadata={}
    ))
    
    store.register_feature(FeatureDefinition(
        name="liquidity_score",
        feature_type=FeatureType.MARKET,
        compute_mode=ComputeMode.BATCH,
        compute_func=compute_liquidity_score,
        dependencies=[],
        ttl_seconds=3600.0,
        version="1.0",
        description="Liquidity score (volume/market_cap)",
        metadata={}
    ))
    
    # Social features
    store.register_feature(FeatureDefinition(
        name="social_sentiment",
        feature_type=FeatureType.SOCIAL,
        compute_mode=ComputeMode.BATCH,
        compute_func=compute_social_sentiment,
        dependencies=[],
        ttl_seconds=300.0,
        version="1.0",
        description="Social sentiment score (0-1)",
        metadata={}
    ))


# Global feature store
_feature_store: Optional[FeatureStore] = None
_feature_store_lock = threading.Lock()


def get_feature_store() -> FeatureStore:
    """Get the global feature store."""
    global _feature_store
    if _feature_store is None:
        with _feature_store_lock:
            if _feature_store is None:
                _feature_store = FeatureStore()
                register_default_features(_feature_store)
    return _feature_store
