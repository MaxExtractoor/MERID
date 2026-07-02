"""
Unified Signal Schema for Cross-Domain Signal Integration

Provides a consistent schema for all signal types (Kalshi edge, fear/greed, 
volume, debate, news, markets) to be stored and processed together.
"""

from __future__ import annotations

import time
from typing import Any, Dict, Optional, Union
from dataclasses import dataclass, field
from enum import Enum


class SignalType(Enum):
    """Types of signals that can be generated"""
    KALSHI_EDGE = "kalshi_edge"
    FEAR_GREED = "fear_greed"
    NEWS_SENTIMENT = "news_sentiment"
    VOLUME_ANOMALY = "volume_anomaly"
    DEBATE_RISK = "debate_risk"
    ORDERBOOK_IMBALANCE = "orderbook_imbalance"
    CROSS_DOMAIN = "cross_domain"


class SignalDomain(Enum):
    """Domain categories for signals"""
    CRYPTO = "crypto"
    PREDICTION = "prediction"
    EQUITY = "equity"
    BETTING = "betting"
    MACRO = "macro"


@dataclass
class UnifiedSignal:
    """Unified signal schema for cross-domain integration"""
    
    # Core identification
    signal_id: str
    symbol: str
    signal_type: Union[SignalType, str]
    domain: Union[SignalDomain, str]
    source: str
    
    # Signal content
    features: Dict[str, Any] = field(default_factory=dict)
    
    # Timing and metadata
    generated_at: float = field(default_factory=time.time)
    confidence: float = 0.5  # 0-1 confidence score
    strength: float = 0.5    # 0-1 signal strength
    
    # Optional fields for specific signal types
    edge_bps: Optional[float] = None
    liquidity_score: Optional[float] = None
    risk_score: Optional[float] = None
    
    # Suppression/gating information
    suppressed: bool = False
    suppressed_reason: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary format for storage"""
        return {
            "signal_id": self.signal_id,
            "symbol": self.symbol,
            "signal_type": self.signal_type.value if isinstance(self.signal_type, SignalType) else self.signal_type,
            "domain": self.domain.value if isinstance(self.domain, SignalDomain) else self.domain,
            "source": self.source,
            "features": self.features,
            "generated_at": self.generated_at,
            "confidence": self.confidence,
            "strength": self.strength,
            "edge_bps": self.edge_bps,
            "liquidity_score": self.liquidity_score,
            "risk_score": self.risk_score,
            "suppressed": self.suppressed,
            "suppressed_reason": self.suppressed_reason,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "UnifiedSignal":
        """Create from dictionary format"""
        # Convert string enums back to enum objects if possible
        signal_type = data.get("signal_type", "")
        if isinstance(signal_type, str):
            try:
                signal_type = SignalType(signal_type)
            except ValueError:
                pass  # Keep as string if not a valid enum
        
        domain = data.get("domain", "")
        if isinstance(domain, str):
            try:
                domain = SignalDomain(domain)
            except ValueError:
                pass  # Keep as string if not a valid enum
        
        return cls(
            signal_id=data["signal_id"],
            symbol=data["symbol"],
            signal_type=signal_type,
            domain=domain,
            source=data["source"],
            features=data.get("features", {}),
            generated_at=data.get("generated_at", time.time()),
            confidence=data.get("confidence", 0.5),
            strength=data.get("strength", 0.5),
            edge_bps=data.get("edge_bps"),
            liquidity_score=data.get("liquidity_score"),
            risk_score=data.get("risk_score"),
            suppressed=data.get("suppressed", False),
            suppressed_reason=data.get("suppressed_reason"),
        )


def create_kalshi_signal(
    ticker: str,
    edge_bps: float,
    features: Dict[str, Any],
    confidence: float = 0.5,
    source: str = "kalshi_signals"
) -> UnifiedSignal:
    """Create a Kalshi edge signal with standard format"""
    ts = int(time.time())
    return UnifiedSignal(
        signal_id=f"kal-{ticker}-{ts}",
        symbol=ticker,
        signal_type=SignalType.KALSHI_EDGE,
        domain=SignalDomain.PREDICTION,
        source=source,
        features=features,
        edge_bps=edge_bps,
        confidence=confidence,
        strength=min(1.0, abs(edge_bps) / 100.0),  # Normalize edge to 0-1
    )


def create_fear_greed_signal(
    symbol: str,
    fg_score: float,
    volume_z: float,
    features: Dict[str, Any],
    source: str = "coingecko_live"
) -> UnifiedSignal:
    """Create a fear/greed signal with volume context"""
    ts = int(time.time())
    return UnifiedSignal(
        signal_id=f"fg-{symbol}-{ts}",
        symbol=symbol,
        signal_type=SignalType.FEAR_GREED,
        domain=SignalDomain.CRYPTO,
        source=source,
        features={
            **features,
            "fear_greed_score": fg_score,
            "volume_z_score": volume_z,
        },
        confidence=0.7,  # Fear/greed is generally reliable
        strength=abs(fg_score - 0.5) * 2,  # Convert 0-1 to 0-1 strength
    )


def create_news_sentiment_signal(
    symbol: str,
    sentiment_score: float,
    intensity: float,
    features: Dict[str, Any],
    source: str = "news_reddit_x"
) -> UnifiedSignal:
    """Create a news sentiment signal"""
    ts = int(time.time())
    return UnifiedSignal(
        signal_id=f"news-{symbol}-{ts}",
        symbol=symbol,
        signal_type=SignalType.NEWS_SENTIMENT,
        domain=SignalDomain.PREDICTION,
        source=source,
        features={
            **features,
            "news_sentiment_score": sentiment_score,
            "news_intensity": intensity,
        },
        confidence=0.6,
        strength=abs(sentiment_score) * intensity,  # Combine sentiment and intensity
    )


def create_debate_risk_signal(
    symbol: str,
    multiplier: float,
    status: str,
    features: Dict[str, Any],
    source: str = "debate_system"
) -> UnifiedSignal:
    """Create a debate risk signal"""
    ts = int(time.time())
    return UnifiedSignal(
        signal_id=f"debate-{symbol}-{ts}",
        symbol=symbol,
        signal_type=SignalType.DEBATE_RISK,
        domain=SignalDomain.PREDICTION,
        source=source,
        features={
            **features,
            "debate_multiplier": multiplier,
            "debate_status": status,
        },
        confidence=0.8,  # Debate system is high confidence
        strength=abs(multiplier - 1.0),  # Distance from neutral multiplier
    )


def suppress_signal(
    signal: UnifiedSignal,
    reason: str,
    new_confidence: Optional[float] = None
) -> UnifiedSignal:
    """Create a suppressed version of a signal"""
    signal.suppressed = True
    signal.suppressed_reason = reason
    if new_confidence is not None:
        signal.confidence = new_confidence
    return signal
