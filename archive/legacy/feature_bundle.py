"""
Feature Bundle Data Structures for 15m Execution Shell

Defines the structured feature bundle that 15m execution agents consume.
All non-15m agents produce features, not trades.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional
from datetime import datetime


@dataclass
class FeatureDict:
    """Typed dictionary for feature values with metadata."""
    features: Dict[str, float] = field(default_factory=dict)
    timestamp: Optional[datetime] = None
    source_agent: str = ""
    confidence: float = 1.0
    
    def get(self, key: str, default: float = 0.0) -> float:
        """Get feature value with default."""
        return self.features.get(key, default)
    
    def has(self, key: str) -> bool:
        """Check if feature exists."""
        return key in self.features


@dataclass
class FifteenMinuteFeatureBundle:
    """
    Complete feature bundle for 15m execution decision.
    
    This is the ONLY input that 15m execution agents receive.
    All other agents (multi-timeframe, sentiment, macro, etc.) populate this bundle.
    """
    
    # Native 15m technical features
    ts_15m: FeatureDict = field(default_factory=FeatureDict)
    
    # Lower timeframe microstructure aggregates (1m, 5m)
    ts_lower_tf: FeatureDict = field(default_factory=FeatureDict)
    
    # Higher timeframe regime flags (1h, 4h, daily, weekly)
    ts_higher_tf: FeatureDict = field(default_factory=FeatureDict)
    
    # Sentiment/news/social features
    sentiment: FeatureDict = field(default_factory=FeatureDict)
    
    # Macro / cross-asset features
    macro: FeatureDict = field(default_factory=FeatureDict)
    
    # Meta/confidence signals from ensemble agents
    confidence_signals: FeatureDict = field(default_factory=FeatureDict)
    
    # Volatility regime features
    volatility: FeatureDict = field(default_factory=FeatureDict)
    
    # Metadata
    asset: str = ""
    timestamp: Optional[datetime] = None
    bundle_version: str = "1.0"
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "ts_15m": self.ts_15m.features,
            "ts_lower_tf": self.ts_lower_tf.features,
            "ts_higher_tf": self.ts_higher_tf.features,
            "sentiment": self.sentiment.features,
            "macro": self.macro.features,
            "confidence_signals": self.confidence_signals.features,
            "volatility": self.volatility.features,
            "asset": self.asset,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            "bundle_version": self.bundle_version,
        }
    
    def get_feature(self, namespace: str, key: str, default: float = 0.0) -> float:
        """Get feature from specific namespace."""
        namespace_map = {
            "ts_15m": self.ts_15m,
            "ts_lower_tf": self.ts_lower_tf,
            "ts_higher_tf": self.ts_higher_tf,
            "sentiment": self.sentiment,
            "macro": self.macro,
            "confidence_signals": self.confidence_signals,
            "volatility": self.volatility,
        }
        
        fd = namespace_map.get(namespace)
        if fd:
            return fd.get(key, default)
        return default
    
    def has_feature(self, namespace: str, key: str) -> bool:
        """Check if feature exists in namespace."""
        namespace_map = {
            "ts_15m": self.ts_15m,
            "ts_lower_tf": self.ts_lower_tf,
            "ts_higher_tf": self.ts_higher_tf,
            "sentiment": self.sentiment,
            "macro": self.macro,
            "confidence_signals": self.confidence_signals,
            "volatility": self.volatility,
        }
        
        fd = namespace_map.get(namespace)
        if fd:
            return fd.has(key)
        return False


@dataclass
class TradeDecision:
    """
    Decision output from 15m execution agent.
    
    Only 15m agents with role=execution may produce this.
    """
    
    asset: str
    timeframe: str
    side: str  # "yes" or "no"
    confidence: float  # 0.0 to 1.0
    edge_estimate: float
    size_pct: float  # Position size as % of bankroll
    market_id: str
    reason: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
    timestamp: Optional[datetime] = None
    
    # Guardrail metadata
    pipeline_id: str = ""
    decision_agent: str = ""
    
    # Extended observability metadata
    feature_summary: Dict[str, Any] = field(default_factory=dict)  # Per-namespace feature summary
    feature_time_window: tuple[Optional[datetime], Optional[datetime]] = (None, None)  # [t_start, t_end]
    features_fingerprint: str = ""  # Hash of feature bundle for auditability
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "asset": self.asset,
            "timeframe": self.timeframe,
            "side": self.side,
            "confidence": self.confidence,
            "edge_estimate": self.edge_estimate,
            "size_pct": self.size_pct,
            "market_id": self.market_id,
            "reason": self.reason,
            "metadata": self.metadata,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            "pipeline_id": self.pipeline_id,
            "decision_agent": self.decision_agent,
            "feature_summary": self.feature_summary,
            "feature_time_window": [
                self.feature_time_window[0].isoformat() if self.feature_time_window[0] else None,
                self.feature_time_window[1].isoformat() if self.feature_time_window[1] else None,
            ],
            "features_fingerprint": self.features_fingerprint,
        }
    
    def validate_guardrails(self) -> tuple[bool, str]:
        """
        Validate that this decision meets guardrails.
        
        Returns (is_valid, error_message).
        """
        if self.timeframe != "15m":
            return False, f"Invalid timeframe: {self.timeframe} (must be 15m)"
        
        if self.asset not in {"BTC", "ETH", "SOL", "XRP", "DOGE"}:
            return False, f"Invalid asset: {self.asset} (must be BTC/ETH/SOL/XRP/DOGE)"
        
        if not 0.0 <= self.confidence <= 1.0:
            return False, f"Invalid confidence: {self.confidence} (must be 0.0-1.0)"
        
        if not 0.0 <= self.size_pct <= 1.0:
            return False, f"Invalid size_pct: {self.size_pct} (must be 0.0-1.0)"
        
        if not self.pipeline_id:
            return False, "Missing pipeline_id (guardrail metadata)"
        
        if not self.decision_agent:
            return False, "Missing decision_agent (guardrail metadata)"
        
        return True, ""
