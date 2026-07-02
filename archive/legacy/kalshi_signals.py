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

import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from merid.signals.decay import DecayEnvelope, SignalDomain
from utils.logger import get_logger

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
        """Generate signal_id if not provided."""
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
        """Generate edge signals from Kalshi market data and agent snapshots.

        Pulls edge data from:
        1. MarketMoodBus for sentiment-driven edges
        2. Active MarketSnapshot edges from prediction model

        Returns actionable MarketEdgeSignal objects for the SignalStore.
        """
        signals = []

        try:
            # Import here to avoid circular dependencies
            from merid.event_venues.kalshi.venue_adapter import get_kalshi_venue_adapter
            from merid.prediction.model import get_active_snapshots
            from merid.sentiment.market_mood_bus import get_market_mood_bus

            adapter = get_kalshi_venue_adapter()
            mood_bus = get_market_mood_bus()

            # Get instruments (markets) for crypto category
            instruments = await adapter.list_instruments(category="crypto", active_only=True)

            # Get active snapshots from prediction model
            active_snapshots = get_active_snapshots()
            snapshot_map = {s.market_id: s for s in active_snapshots}

            for inst in instruments[:20]:  # Limit to 20 for performance
                ticker = inst.id
                asset = self._extract_asset(ticker)
                timeframe = self._extract_timeframe(ticker)

                # Try to get snapshot edges first
                snapshot = snapshot_map.get(ticker)
                if snapshot and snapshot.edges:
                    # Find best speculative edge
                    spec_edges = [e for e in snapshot.edges if e.edge_type == "speculative"]
                    if spec_edges:
                        best = max(spec_edges, key=lambda e: e.net_edge)
                        if best.net_edge > 0:  # Only emit positive edges
                            signals.append(MarketEdgeSignal(
                                ticker=ticker,
                                asset=asset,
                                timeframe=timeframe,
                                question=inst.question or "",
                                implied_prob=float(best.market_prob),
                                model_prob=float(best.model_prob),
                                ev_cents=float(best.net_edge) * 100,  # Convert to cents
                                edge_pct=float(best.net_edge) * 100,  # As percentage
                                confidence=float(best.confidence),
                                confidence_bucket="high" if best.confidence > 0.7 else "medium" if best.confidence > 0.4 else "low",
                                sizing_tier="normal" if best.net_edge > 0.05 else "reduced",
                                source="kalshi_edge",
                            ))
                            continue

                # Fallback: Try MarketMoodBus sentiment context
                for tf in ["15m", "1h", "daily"]:
                    context = mood_bus.get_context(asset, tf)
                    if context and context.swarm_consensus_prob is not None:
                        # Use swarm consensus as model probability
                        implied_prob = context.kalshi_price
                        model_prob = context.swarm_consensus_prob
                        edge = model_prob - implied_prob

                        if abs(edge) > 0.05:  # CONSERVATIVE: 5% minimum edge
                            signals.append(MarketEdgeSignal(
                                ticker=ticker,
                                asset=asset,
                                timeframe=timeframe,
                                question=inst.question or "",
                                implied_prob=implied_prob,
                                model_prob=model_prob,
                                ev_cents=edge * 100,
                                edge_pct=edge * 100,
                                confidence=context.swarm_confidence or 0.5,
                                confidence_bucket="high" if (context.swarm_confidence or 0) > 0.7 else "medium",
                                sizing_tier="normal" if abs(edge) > 0.05 else "reduced",
                                source="swarm_consensus",
                            ))
                        break

            if signals:
                logger.info(
                    f"Generated {len(signals)} edge signals from {len(instruments)} instruments"
                )
            else:
                logger.debug("No actionable edge signals generated")

        except Exception as exc:
            logger.error(f"Edge signal generation failed: {exc}")

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


# ── Consensus-Gated Signal Generator ───────────────────────────────────────

@dataclass
class GatedSignalResult:
    """Result of consensus-gated signal generation."""
    signal: Any
    ticker: str
    consensus_status: str  # ready, forming, conflicted, none
    consensus_direction: Optional[str]  # yes/no/neutral if available
    consensus_confidence: float
    sim_only: bool
    gated: bool  # True if signal was blocked by consensus
    gate_reason: str


class ConsensusGatedSignalGenerator:
    """Wraps KalshiSignalGenerator with consensus gating.
    
    This is the PRIMARY interface for signal generation in the market-driven
    architecture. It ensures all signals are checked against swarm consensus
    before being emitted, with clear logging of market IDs and sim/live status.
    
    DISCOVER → ANALYZE → CONSENSUS → SIZE → EXECUTE pipeline:
    - Signals are only generated for markets with READY consensus
    - sim_only=True signals are marked but still flow through (for simulation)
    - Clear logging shows: "Consensus for KXBTC-15M: LIVE=YES @ 72%"
    """
    
    def __init__(self):
        self._base_generator = KalshiSignalGenerator()
        self._last_gated_results: List[GatedSignalResult] = []
    
    async def generate_all_gated(self, now: Optional[float] = None) -> List[GatedSignalResult]:
        """Generate consensus-gated signals for all Kalshi markets.
        
        Returns:
            List of GatedSignalResult with consensus status for each signal.
            Only signals that pass consensus checks have gated=False.
        """
        now = now or time.time()
        results: List[GatedSignalResult] = []
        
        # Get base signals
        base_signals = await self._base_generator.generate_all(now)
        
        # Get consensus aggregator
        from merid.swarm.consensus_aggregator import get_consensus_aggregator
        aggregator = get_consensus_aggregator()
        
        for signal in base_signals:
            ticker = getattr(signal, 'ticker', '')
            asset = getattr(signal, 'asset', '')
            timeframe = getattr(signal, 'timeframe', '1h')
            
            # Look up consensus for this market
            consensus = aggregator.get_consensus(asset, timeframe)
            
            if consensus is None:
                # No consensus available - gate the signal
                results.append(GatedSignalResult(
                    signal=signal,
                    ticker=ticker,
                    consensus_status="none",
                    consensus_direction=None,
                    consensus_confidence=0.0,
                    sim_only=True,  # Default to sim when no consensus
                    gated=True,
                    gate_reason="No consensus available (insufficient agent proposals)"
                ))
                logger.debug(
                    f"Signal gated for {ticker}: No consensus available"
                )
                continue
            
            # Check consensus status
            if consensus.status.value != "ready":
                results.append(GatedSignalResult(
                    signal=signal,
                    ticker=ticker,
                    consensus_status=consensus.status.value,
                    consensus_direction=consensus.consensus_direction,
                    consensus_confidence=consensus.consensus_confidence,
                    sim_only=True,
                    gated=True,
                    gate_reason=f"Consensus status: {consensus.status.value}"
                ))
                logger.debug(
                    f"Signal gated for {ticker}: Consensus {consensus.status.value}"
                )
                continue
            
            # Check if signal direction aligns with consensus
            signal_direction = getattr(signal, 'direction', None)
            if signal_direction and consensus.consensus_direction != signal_direction:
                # Direction mismatch - signal is contrarian, mark as sim_only
                sim_only = True
                gate_reason = f"Direction mismatch: signal={signal_direction}, consensus={consensus.consensus_direction}"
            else:
                sim_only = False
                gate_reason = "Consensus aligned"
            
            # Log with explicit market ID
            mode = "SIM" if sim_only else "LIVE"
            logger.info(
                f"Signal approved for {ticker}: "
                f"{mode}={consensus.consensus_direction.upper()} @ "
                f"{consensus.consensus_confidence:.0%} consensus "
                f"({gate_reason})"
            )
            
            results.append(GatedSignalResult(
                signal=signal,
                ticker=ticker,
                consensus_status="ready",
                consensus_direction=consensus.consensus_direction,
                consensus_confidence=consensus.consensus_confidence,
                sim_only=sim_only,
                gated=False,
                gate_reason=gate_reason
            ))
        
        self._last_gated_results = results
        
        # Summary log
        approved = sum(1 for r in results if not r.gated)
        gated = len(results) - approved
        sim_count = sum(1 for r in results if r.sim_only)
        
        logger.info(
            f"Consensus-gated signals: {approved} approved ({sim_count} sim), "
            f"{gated} gated"
        )
        
        return results
    
    def get_live_signals(self) -> List[Any]:
        """Get only live (non-sim) signals that passed consensus."""
        return [
            r.signal for r in self._last_gated_results
            if not r.gated and not r.sim_only
        ]
    
    def get_sim_signals(self) -> List[Any]:
        """Get simulation-only signals (includes both gated and approved sim)."""
        return [
            r.signal for r in self._last_gated_results
            if r.sim_only or r.gated
        ]
    
    def get_signals_by_ticker(self, ticker: str) -> List[GatedSignalResult]:
        """Get all signal results for a specific ticker."""
        return [r for r in self._last_gated_results if r.ticker.upper() == ticker.upper()]


# ── Singleton ─────────────────────────────────────────────────────────────

_filter: Optional[KalshiSignalFilter] = None
# LEGACY REMOVAL: Threading lock removed - causing deadlock during startup
# Single-threaded FastAPI startup doesn't need lock protection

# NEW: Consensus-gated singleton
_gated_generator: Optional[ConsensusGatedSignalGenerator] = None
# LEGACY REMOVAL: Threading lock removed - causing deadlock during startup
# Single-threaded FastAPI startup doesn't need lock protection
_generator: Optional[KalshiSignalGenerator] = None
# LEGACY REMOVAL: Threading lock removed - causing deadlock during startup
# Single-threaded FastAPI startup doesn't need lock protection


def get_kalshi_signal_generator() -> KalshiSignalGenerator:
    """Get or create the singleton KalshiSignalGenerator."""
    global _generator
    if _generator is None:
        _generator = KalshiSignalGenerator()
    return _generator


def get_consensus_gated_generator() -> ConsensusGatedSignalGenerator:
    """Get or create the singleton ConsensusGatedSignalGenerator.

    This is the PRIMARY interface for market-driven signal generation.
    All signals are checked against swarm consensus before being emitted.
    """
    global _gated_generator
    if _gated_generator is None:
        _gated_generator = ConsensusGatedSignalGenerator()
    return _gated_generator


def reset_kalshi_signal_generator() -> None:
    """Reset singletons (for testing)."""
    global _generator, _gated_generator
    _generator = None
    _gated_generator = None
