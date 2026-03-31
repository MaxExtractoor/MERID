"""Kalshi Signal Generator — prediction market signals for MERID swarm.

Generates MERID-native signals from Kalshi market data:
- MarketEdgeSignal: Edge/EV opportunities from edge endpoint
- LiquiditySignal: Spread/depth alerts from liquidity monitor
- VolumeAnomalySignal: Unusual volume spikes
- KalshiRiskSignal: Risk events (drawdown, kill switch, rate limits)

Signals follow MERID's standard schema:
- DecayEnvelope-aware
- Tagged with venue="kalshi", domain="prediction"
- Stored in SignalStore for agent consumption

Usage::

    generator = get_kalshi_signal_generator()
    signals = await generator.generate_all()
    
    for signal in signals:
        signal_store.store_signal(signal.to_dict())
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from merid.signals.decay import DecayEnvelope, SignalDomain
from utils.logger import get_logger

try:
    from merid.event_venues.kalshi.venue_adapter import (
        get_kalshi_venue_adapter,
        reset_kalshi_venue_adapter,
    )
except Exception:  # pragma: no cover — missing deps in some envs
    get_kalshi_venue_adapter = None  # type: ignore[assignment]
    reset_kalshi_venue_adapter = None  # type: ignore[assignment]

logger = get_logger("merid.signals.kalshi")


# ── Signal Types ──────────────────────────────────────────────────────────

class KalshiSignalType(str, Enum):
    """Kalshi-specific signal types."""
    MARKET_EDGE = "market_edge"
    LIQUIDITY = "liquidity"
    VOLUME_ANOMALY = "volume_anomaly"
    RISK_EVENT = "risk_event"


class LiquiditySeverity(str, Enum):
    """Liquidity alert severity levels."""
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class RiskEventCategory(str, Enum):
    """Risk event categories."""
    CIRCUIT_BREAKER = "circuit_breaker"
    DRAWDOWN = "drawdown"
    RATE_LIMIT = "rate_limit"
    LOSS_CAP = "loss_cap"
    GENERAL = "general"


# ── Signal Models ─────────────────────────────────────────────────────────

@dataclass
class MarketEdgeSignal:
    """Edge/EV signal for a Kalshi market.
    
    Generated from /kalshi/edge endpoint or edge model.
    Represents a mispricing between implied and model probability.
    """
    signal_id: str = ""
    signal_type: str = KalshiSignalType.MARKET_EDGE.value
    venue: str = "kalshi"
    domain: str = "prediction"
    
    # Market identification
    ticker: str = ""
    asset: str = ""                    # BTC, ETH, SOL, etc.
    timeframe: str = ""                # 1h, 24h, weekly, etc.
    question: str = ""
    
    # Edge metrics
    implied_prob: float = 0.0          # Market mid price (0-1)
    model_prob: float = 0.0            # Our fair value (0-1)
    ev_cents: float = 0.0              # EV per contract in cents
    edge_pct: float = 0.0              # Edge as % of implied
    
    # Confidence and sizing
    confidence: float = 0.0            # 0-1 model confidence
    confidence_bucket: str = "low"     # low/medium/high
    sizing_tier: str = "normal"        # normal/reduced/boosted/halted
    
    # Timing
    timestamp: float = field(default_factory=time.time)
    decay_weight: float = 1.0
    
    # Source
    source: str = "kalshi_edge"        # kalshi_edge, edge_model, synthetic
    
    def __post_init__(self):
        """Generate signal_id if not provided; coerce enum fields to their string values."""
        if isinstance(self.signal_type, KalshiSignalType):
            self.signal_type = self.signal_type.value
        if not self.signal_id:
            self.signal_id = f"edge-{self.ticker}-{int(self.timestamp)}"
    
    def is_actionable(self, min_edge_pct: float = 2.0, min_confidence: float = 0.3) -> bool:
        """Check if signal meets minimum thresholds for action."""
        return (
            abs(self.edge_pct) >= min_edge_pct and
            self.confidence >= min_confidence and
            self.sizing_tier != "halted"
        )
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "signal_id": self.signal_id,
            "signal_type": self.signal_type,
            "venue": self.venue,
            "domain": self.domain,
            "ticker": self.ticker,
            "asset": self.asset,
            "timeframe": self.timeframe,
            "question": self.question,
            "implied_prob": round(self.implied_prob, 4),
            "model_prob": round(self.model_prob, 4),
            "ev_cents": round(self.ev_cents, 2),
            "edge_pct": round(self.edge_pct, 2),
            "confidence": round(self.confidence, 3),
            "confidence_bucket": self.confidence_bucket,
            "sizing_tier": self.sizing_tier,
            "timestamp": self.timestamp,
            "decay_weight": round(self.decay_weight, 4),
            "source": self.source,
            "actionable": self.is_actionable(),
        }


@dataclass
class LiquiditySignal:
    """Liquidity alert for a Kalshi market.
    
    Generated from liquidity monitor.
    Warns about poor market conditions (wide spreads, thin books).
    """
    signal_id: str = ""
    signal_type: str = KalshiSignalType.LIQUIDITY.value
    venue: str = "kalshi"
    domain: str = "prediction"
    
    # Market identification
    ticker: str = ""
    
    # Liquidity metrics
    spread_cents: float = 0.0          # Bid-ask spread in cents
    spread_pct: float = 0.0            # Spread as % of mid
    depth_contracts: float = 0.0       # Total contracts in book
    
    # Alert details
    alert_type: str = ""               # wide_spread, thin_book, spread_spike, depth_drop
    severity: str = LiquiditySeverity.INFO.value
    message: str = ""
    
    # Timing
    timestamp: float = field(default_factory=time.time)
    
    def __post_init__(self):
        if isinstance(self.signal_type, KalshiSignalType):
            self.signal_type = self.signal_type.value
        if isinstance(self.severity, LiquiditySeverity):
            self.severity = self.severity.value
        if not self.signal_id:
            self.signal_id = f"liq-{self.ticker}-{int(self.timestamp)}"
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "signal_id": self.signal_id,
            "signal_type": self.signal_type,
            "venue": self.venue,
            "domain": self.domain,
            "ticker": self.ticker,
            "spread_cents": round(self.spread_cents, 2),
            "spread_pct": round(self.spread_pct, 2),
            "depth_contracts": round(self.depth_contracts, 0),
            "alert_type": self.alert_type,
            "severity": self.severity,
            "message": self.message,
            "timestamp": self.timestamp,
        }


@dataclass
class VolumeAnomalySignal:
    """Volume anomaly detection for a Kalshi market.
    
    Generated from volume monitor.
    Detects unusual volume spikes using z-score analysis.
    """
    signal_id: str = ""
    signal_type: str = KalshiSignalType.VOLUME_ANOMALY.value
    venue: str = "kalshi"
    domain: str = "prediction"
    
    # Market identification
    ticker: str = ""
    asset: str = ""
    
    # Volume metrics
    current_volume: float = 0.0
    rolling_mean: float = 0.0
    rolling_std: float = 0.0
    z_score: float = 0.0               # Deviation from mean in std devs
    
    # Alert details
    severity: str = "info"             # info/warning/critical
    direction: str = "spike"           # spike/drop
    
    # Timing
    timestamp: float = field(default_factory=time.time)
    
    def __post_init__(self):
        if isinstance(self.signal_type, KalshiSignalType):
            self.signal_type = self.signal_type.value
        if not self.signal_id:
            self.signal_id = f"vol-{self.ticker}-{int(self.timestamp)}"
    
    def is_significant(self, threshold: float = 3.0) -> bool:
        """Check if anomaly exceeds significance threshold."""
        return abs(self.z_score) >= threshold
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "signal_id": self.signal_id,
            "signal_type": self.signal_type,
            "venue": self.venue,
            "domain": self.domain,
            "ticker": self.ticker,
            "asset": self.asset,
            "current_volume": round(self.current_volume, 0),
            "rolling_mean": round(self.rolling_mean, 0),
            "rolling_std": round(self.rolling_std, 2),
            "z_score": round(self.z_score, 2),
            "severity": self.severity,
            "direction": self.direction,
            "timestamp": self.timestamp,
            "significant": self.is_significant(),
        }


@dataclass
class KalshiRiskSignal:
    """Risk event signal from Kalshi risk manager.
    
    Generated from /kalshi/risk/events endpoint.
    Propagates risk alerts into the global MERID signal layer.
    """
    signal_id: str = ""
    signal_type: str = KalshiSignalType.RISK_EVENT.value
    venue: str = "kalshi"
    domain: str = "prediction"
    
    # Event details
    category: str = RiskEventCategory.GENERAL.value
    severity: str = "info"             # info/warning/critical
    title: str = ""
    detail: str = ""
    
    # Metrics (if applicable)
    drawdown_pct: Optional[float] = None
    rate_limit_count: Optional[int] = None
    daily_loss_usd: Optional[float] = None
    
    # Timing
    timestamp: float = field(default_factory=time.time)
    
    def __post_init__(self):
        if isinstance(self.signal_type, KalshiSignalType):
            self.signal_type = self.signal_type.value
        if isinstance(self.category, RiskEventCategory):
            self.category = self.category.value
        if not self.signal_id:
            self.signal_id = f"risk-{self.category}-{int(self.timestamp)}"
    
    def to_dict(self) -> Dict[str, Any]:
        data = {
            "signal_id": self.signal_id,
            "signal_type": self.signal_type,
            "venue": self.venue,
            "domain": self.domain,
            "category": self.category,
            "severity": self.severity,
            "title": self.title,
            "detail": self.detail,
            "timestamp": self.timestamp,
        }
        
        # Add optional metrics if present
        if self.drawdown_pct is not None:
            data["drawdown_pct"] = round(self.drawdown_pct, 2)
        if self.rate_limit_count is not None:
            data["rate_limit_count"] = self.rate_limit_count
        if self.daily_loss_usd is not None:
            data["daily_loss_usd"] = round(self.daily_loss_usd, 2)
        
        return data


# ── Factory helpers ───────────────────────────────────────────────────

def make_market_edge_signal(**kwargs) -> MarketEdgeSignal:
    """Factory for MarketEdgeSignal — accepts all documented field names."""
    return MarketEdgeSignal(**kwargs)


def make_liquidity_signal(**kwargs) -> LiquiditySignal:
    """Factory for LiquiditySignal — accepts all documented field names."""
    return LiquiditySignal(**kwargs)


def make_volume_anomaly_signal(**kwargs) -> VolumeAnomalySignal:
    """Factory for VolumeAnomalySignal — accepts all documented field names."""
    return VolumeAnomalySignal(**kwargs)


def make_kalshi_risk_signal(**kwargs) -> KalshiRiskSignal:
    """Factory for KalshiRiskSignal — accepts all documented field names."""
    return KalshiRiskSignal(**kwargs)


# ── Signal Generator ──────────────────────────────────────────────────────

class KalshiSignalGenerator:
    """Generates MERID signals from Kalshi market data.
    
    Pulls from:
    - KalshiVenueAdapter for market data
    - Edge endpoint/model for EV signals
    - Liquidity monitor for spread alerts
    - Volume monitor for anomalies
    - Risk manager for risk events
    
    Outputs:
    - List of typed signals (MarketEdgeSignal, etc.)
    - Ready for SignalStore persistence
    """
    
    def __init__(self):
        self._last_generation: float = 0.0
        self._signal_cache: List[Any] = []
    
    async def generate_all(self, now: Optional[float] = None) -> List[Any]:
        """Generate all Kalshi signals.
        
        Returns:
            List of signal objects (mixed types)
        """
        now = now or time.time()
        signals: List[Any] = []
        
        try:
            # Generate edge signals
            edge_signals = await self._generate_edge_signals(now)
            signals.extend(edge_signals)
            
            # Generate liquidity signals
            liq_signals = await self._generate_liquidity_signals(now)
            signals.extend(liq_signals)
            
            # Generate volume anomaly signals
            vol_signals = await self._generate_volume_signals(now)
            signals.extend(vol_signals)
            
            # Generate risk event signals
            risk_signals = await self._generate_risk_signals(now)
            signals.extend(risk_signals)
            
            self._last_generation = now
            self._signal_cache = signals
            
            logger.info(
                f"Generated {len(signals)} Kalshi signals: "
                f"{len(edge_signals)} edge, {len(liq_signals)} liquidity, "
                f"{len(vol_signals)} volume, {len(risk_signals)} risk"
            )
            
        except Exception as exc:
            logger.error(f"Kalshi signal generation failed: {exc}")
            return []
        
        return signals
    
    async def _generate_edge_signals(self, now: float) -> List[MarketEdgeSignal]:
        """Generate edge signals from Kalshi edge endpoint."""
        signals = []
        
        try:
            # Import here to avoid circular dependencies
            from merid.event_venues.kalshi.venue_adapter import get_kalshi_venue_adapter
            
            adapter = get_kalshi_venue_adapter()
            
            # Get instruments (markets) for crypto category
            instruments = await adapter.list_instruments(category="crypto", active_only=True)
            
            # For each market, check if we have edge data
            # In production, this would call /kalshi/edge or edge model
            # For now, generate synthetic edge signals for active markets
            for inst in instruments[:10]:  # Limit to 10 for performance
                # Extract asset and timeframe from ticker (e.g. "BTC-24FEB-50K-YES" → BTC, 24h)
                asset = self._extract_asset(inst.id)
                timeframe = self._extract_timeframe(inst.id)
                
                # Synthetic edge (in production: call edge endpoint)
                edge_signal = MarketEdgeSignal(
                    ticker=inst.id,
                    asset=asset,
                    timeframe=timeframe,
                    question=f"Market {inst.id}",
                    implied_prob=0.55,  # Placeholder
                    model_prob=0.57,    # Placeholder
                    ev_cents=2.0,
                    edge_pct=3.6,
                    confidence=0.5,
                    confidence_bucket="medium",
                    sizing_tier="normal",
                    timestamp=now,
                    source="synthetic",
                )
                
                # Only emit if actionable
                if edge_signal.is_actionable():
                    signals.append(edge_signal)
            
        except Exception as exc:
            logger.warning(f"Edge signal generation failed: {exc}")
        
        return signals
    
    async def _generate_liquidity_signals(self, now: float) -> List[LiquiditySignal]:
        """Generate liquidity alerts from liquidity monitor."""
        signals = []
        
        try:
            # In production: call liquidity monitor API
            # For now: no signals (requires live monitor)
            pass
        except Exception as exc:
            logger.warning(f"Liquidity signal generation failed: {exc}")
        
        return signals
    
    async def _generate_volume_signals(self, now: float) -> List[VolumeAnomalySignal]:
        """Generate volume anomaly signals from volume monitor."""
        signals = []
        
        try:
            # In production: call volume anomaly API
            # For now: no signals (requires live monitor)
            pass
        except Exception as exc:
            logger.warning(f"Volume signal generation failed: {exc}")
        
        return signals
    
    async def _generate_risk_signals(self, now: float) -> List[KalshiRiskSignal]:
        """Generate risk event signals from risk manager."""
        signals = []
        
        try:
            # In production: call /kalshi/risk/events
            # For now: no signals (requires live risk events)
            pass
        except Exception as exc:
            logger.warning(f"Risk signal generation failed: {exc}")
        
        return signals
    
    def _extract_asset(self, ticker: str) -> str:
        """Extract asset symbol from Kalshi ticker."""
        # Simple heuristic: first word before dash
        parts = ticker.split("-")
        if parts:
            asset = parts[0].upper()
            # Map common assets
            if asset in ("BTC", "ETH", "SOL", "DOGE", "XRP", "ADA"):
                return asset
        return "UNKNOWN"
    
    def _extract_timeframe(self, ticker: str) -> str:
        """Extract timeframe from Kalshi ticker."""
        # Simple heuristic: look for date patterns
        ticker_lower = ticker.lower()
        if "24h" in ticker_lower or "daily" in ticker_lower:
            return "24h"
        if "weekly" in ticker_lower or "week" in ticker_lower:
            return "weekly"
        if "hourly" in ticker_lower or "1h" in ticker_lower:
            return "1h"
        return "unknown"
    
    def get_last_signals(self) -> List[Any]:
        """Get cached signals from last generation."""
        return self._signal_cache


# ── Singleton ─────────────────────────────────────────────────────────────

_generator: Optional[KalshiSignalGenerator] = None


def get_kalshi_signal_generator() -> KalshiSignalGenerator:
    """Get or create the singleton KalshiSignalGenerator."""
    global _generator
    if _generator is None:
        _generator = KalshiSignalGenerator()
    return _generator


def reset_kalshi_signal_generator() -> None:
    """Reset singleton (for testing)."""
    global _generator
    _generator = None
