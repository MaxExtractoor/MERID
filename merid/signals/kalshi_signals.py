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


# ── Configurable thresholds (override via environment or config) ──────────

# Edge signal thresholds
EDGE_MIN_SPREAD_CENTS: float = 1.0       # Minimum spread to compute edge
EDGE_CONFIDENCE_BASE: float = 0.3        # Baseline confidence when data is sparse
EDGE_CONFIDENCE_SPREAD_BONUS: float = 0.4  # Extra confidence from tight spreads
EDGE_SPREAD_NEUTRALISATION: float = 20.0 # Spread % at which model fully reverts to 0.5
EDGE_MODEL_REVERSION_WEIGHT: float = 0.1 # How much model nudges toward 0.5 at max spread

# Liquidity thresholds
LIQUIDITY_WIDE_SPREAD_PCT: float = 8.0   # Spread % considered "wide"
LIQUIDITY_CRITICAL_SPREAD_PCT: float = 15.0  # Spread % considered "critical"
LIQUIDITY_THIN_DEPTH: float = 20.0       # Contracts below this = thin book

# Risk thresholds
RISK_DRAWDOWN_WARN_PCT: float = 5.0      # Portfolio drawdown warning
RISK_DRAWDOWN_CRIT_PCT: float = 10.0     # Portfolio drawdown critical


# ── Signal Generator ──────────────────────────────────────────────────────

class KalshiSignalGenerator:
    """Generates MERID signals from Kalshi market data.

    Pulls from:
    - KalshiVenueAdapter for market data (orderbooks, mid prices)
    - Risk manager for drawdown / kill-switch state
    - crypto_universe for canonical asset validation

    Outputs:
    - List of typed signals (MarketEdgeSignal, LiquiditySignal, etc.)
    - Ready for SignalStore persistence

    All signals are **computed from live data**.  If the data source is
    unavailable the corresponding signal list is empty (graceful degradation).
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

    # ── Edge signals ──────────────────────────────────────────────────

    async def _generate_edge_signals(self, now: float) -> List[MarketEdgeSignal]:
        """Generate edge signals from live market data.

        For each active instrument the implied probability is derived from
        the market mid-price.  A model probability is estimated from the
        bid/ask spread width and recent volume (tighter spread → higher
        confidence that mid reflects fair value).  Edge = model - implied.
        """
        signals: List[MarketEdgeSignal] = []

        try:
            from merid.event_venues.kalshi.venue_adapter import get_kalshi_venue_adapter

            adapter = get_kalshi_venue_adapter()
            instruments = await adapter.list_instruments(
                category="crypto", active_only=True,
            )

            for inst in instruments:
                asset = self._extract_asset(inst.id)
                timeframe = self._extract_timeframe(inst.id)

                # Derive prices from the instrument object when available.
                bid = getattr(inst, "best_bid", None) or getattr(inst, "bid", None)
                ask = getattr(inst, "best_ask", None) or getattr(inst, "ask", None)
                last = getattr(inst, "last_price", None) or getattr(inst, "price", None)
                volume = getattr(inst, "volume", None) or 0

                # Compute mid price (cents) — skip if no price data at all
                if bid is not None and ask is not None:
                    mid_cents = (float(bid) + float(ask)) / 2.0
                    spread_cents = float(ask) - float(bid)
                elif last is not None:
                    mid_cents = float(last)
                    spread_cents = 0.0
                else:
                    # No price data — skip this instrument
                    continue

                if mid_cents <= 0 or mid_cents >= 100:
                    continue  # Out of valid probability range

                implied_prob = mid_cents / 100.0

                # Model probability: nudge toward 0.5 proportional to spread.
                # spread_factor ranges from 1.0 (zero spread) to 0.0 (spread >= EDGE_SPREAD_NEUTRALISATION%).
                # The model reversion shifts implied_prob toward 0.5 by at most EDGE_MODEL_REVERSION_WEIGHT.
                spread_pct = (spread_cents / mid_cents * 100.0) if mid_cents > 0 else 100.0
                spread_factor = max(0.0, min(1.0, 1.0 - spread_pct / EDGE_SPREAD_NEUTRALISATION))
                model_prob = implied_prob + (0.5 - implied_prob) * (1.0 - spread_factor) * EDGE_MODEL_REVERSION_WEIGHT

                # Clamp to valid range
                model_prob = max(0.01, min(0.99, model_prob))

                edge_pct = ((model_prob - implied_prob) / max(implied_prob, 0.01)) * 100.0
                ev_cents = (model_prob - implied_prob) * 100.0  # cents per contract

                # Confidence from spread tightness and volume
                confidence = EDGE_CONFIDENCE_BASE
                if spread_cents < 5:
                    confidence += EDGE_CONFIDENCE_SPREAD_BONUS
                elif spread_cents < 10:
                    confidence += EDGE_CONFIDENCE_SPREAD_BONUS * 0.5
                if volume and float(volume) > 100:
                    confidence = min(1.0, confidence + 0.1)

                confidence_bucket = (
                    "high" if confidence >= 0.7
                    else "medium" if confidence >= 0.4
                    else "low"
                )
                sizing_tier = "normal" if confidence >= 0.4 else "reduced"

                edge_signal = MarketEdgeSignal(
                    ticker=inst.id,
                    asset=asset,
                    timeframe=timeframe,
                    question=getattr(inst, "title", "") or f"Market {inst.id}",
                    implied_prob=round(implied_prob, 4),
                    model_prob=round(model_prob, 4),
                    ev_cents=round(ev_cents, 2),
                    edge_pct=round(edge_pct, 2),
                    confidence=round(confidence, 3),
                    confidence_bucket=confidence_bucket,
                    sizing_tier=sizing_tier,
                    timestamp=now,
                    source="live_market",
                )

                if edge_signal.is_actionable():
                    signals.append(edge_signal)

        except Exception as exc:
            logger.warning(f"Edge signal generation failed: {exc}")

        return signals

    # ── Liquidity signals ─────────────────────────────────────────────

    async def _generate_liquidity_signals(self, now: float) -> List[LiquiditySignal]:
        """Generate liquidity alerts from live orderbook spread and depth."""
        signals: List[LiquiditySignal] = []

        try:
            from merid.event_venues.kalshi.venue_adapter import get_kalshi_venue_adapter

            adapter = get_kalshi_venue_adapter()
            instruments = await adapter.list_instruments(
                category="crypto", active_only=True,
            )

            for inst in instruments:
                bid = getattr(inst, "best_bid", None) or getattr(inst, "bid", None)
                ask = getattr(inst, "best_ask", None) or getattr(inst, "ask", None)
                depth = getattr(inst, "open_interest", None) or getattr(inst, "depth", None) or 0

                if bid is None or ask is None:
                    continue

                bid_f, ask_f = float(bid), float(ask)
                if bid_f <= 0:
                    continue

                spread_cents = ask_f - bid_f
                mid = (bid_f + ask_f) / 2.0
                spread_pct = (spread_cents / mid * 100.0) if mid > 0 else 0.0

                # Determine alert type and severity
                alert_type: Optional[str] = None
                severity = LiquiditySeverity.INFO

                if spread_pct >= LIQUIDITY_CRITICAL_SPREAD_PCT:
                    alert_type = "wide_spread"
                    severity = LiquiditySeverity.CRITICAL
                elif spread_pct >= LIQUIDITY_WIDE_SPREAD_PCT:
                    alert_type = "wide_spread"
                    severity = LiquiditySeverity.WARNING

                if float(depth) < LIQUIDITY_THIN_DEPTH:
                    alert_type = alert_type or "thin_book"
                    if severity == LiquiditySeverity.INFO:
                        severity = LiquiditySeverity.WARNING

                if alert_type is None:
                    continue  # Healthy liquidity — no alert needed

                signals.append(LiquiditySignal(
                    ticker=inst.id,
                    spread_cents=round(spread_cents, 2),
                    spread_pct=round(spread_pct, 2),
                    depth_contracts=float(depth),
                    alert_type=alert_type,
                    severity=severity.value,
                    message=f"Spread {spread_pct:.1f}%, depth {depth}",
                    timestamp=now,
                ))

        except Exception as exc:
            logger.warning(f"Liquidity signal generation failed: {exc}")

        return signals

    # ── Volume anomaly signals ────────────────────────────────────────

    async def _generate_volume_signals(self, now: float) -> List[VolumeAnomalySignal]:
        """Generate volume anomaly signals from instrument volume data.

        Computes a simple z-score relative to the volume mean/std observed
        across all active instruments.  A per-instrument rolling history is
        not available here, so we use the cross-sectional distribution as a
        proxy — instruments with volume far above the group mean get flagged.
        """
        signals: List[VolumeAnomalySignal] = []

        try:
            from merid.event_venues.kalshi.venue_adapter import get_kalshi_venue_adapter

            adapter = get_kalshi_venue_adapter()
            instruments = await adapter.list_instruments(
                category="crypto", active_only=True,
            )

            volumes: List[float] = []
            inst_vols: List[tuple] = []
            for inst in instruments:
                vol = getattr(inst, "volume", None)
                if vol is not None and float(vol) > 0:
                    volumes.append(float(vol))
                    inst_vols.append((inst, float(vol)))

            if len(volumes) < 3:
                return signals  # Not enough data for cross-sectional z-score

            mean_vol = sum(volumes) / len(volumes)
            var = sum((v - mean_vol) ** 2 for v in volumes) / len(volumes)
            std_vol = var ** 0.5 if var > 0 else 1.0

            for inst, vol in inst_vols:
                z = (vol - mean_vol) / std_vol
                if abs(z) < 2.0:
                    continue

                asset = self._extract_asset(inst.id)
                severity = "critical" if abs(z) >= 4.0 else "warning" if abs(z) >= 3.0 else "info"

                signals.append(VolumeAnomalySignal(
                    ticker=inst.id,
                    asset=asset,
                    current_volume=vol,
                    rolling_mean=round(mean_vol, 0),
                    rolling_std=round(std_vol, 2),
                    z_score=round(z, 2),
                    severity=severity,
                    direction="spike" if z > 0 else "drop",
                    timestamp=now,
                ))

        except Exception as exc:
            logger.warning(f"Volume signal generation failed: {exc}")

        return signals

    # ── Risk event signals ────────────────────────────────────────────

    async def _generate_risk_signals(self, now: float) -> List[KalshiRiskSignal]:
        """Generate risk event signals from the risk manager.

        Checks:
        - Global kill switch state
        - Portfolio drawdown percentage
        - Daily PnL loss
        """
        signals: List[KalshiRiskSignal] = []

        try:
            from merid.risk.kill_switches import risk_controller

            # Kill-switch check
            if risk_controller._global_kill:
                signals.append(KalshiRiskSignal(
                    category=RiskEventCategory.CIRCUIT_BREAKER.value,
                    severity="critical",
                    title="Kill switch engaged",
                    detail=risk_controller._kill_details or str(risk_controller._kill_reason),
                    timestamp=now,
                ))

            # Drawdown check
            drawdown = getattr(risk_controller, "_drawdown_pct", None)
            if drawdown is not None:
                dd = float(drawdown)
                if dd >= RISK_DRAWDOWN_CRIT_PCT:
                    signals.append(KalshiRiskSignal(
                        category=RiskEventCategory.DRAWDOWN.value,
                        severity="critical",
                        title="Portfolio drawdown critical",
                        detail=f"Drawdown at {dd:.1f}% (threshold {RISK_DRAWDOWN_CRIT_PCT}%)",
                        drawdown_pct=dd,
                        timestamp=now,
                    ))
                elif dd >= RISK_DRAWDOWN_WARN_PCT:
                    signals.append(KalshiRiskSignal(
                        category=RiskEventCategory.DRAWDOWN.value,
                        severity="warning",
                        title="Portfolio drawdown elevated",
                        detail=f"Drawdown at {dd:.1f}% (threshold {RISK_DRAWDOWN_WARN_PCT}%)",
                        drawdown_pct=dd,
                        timestamp=now,
                    ))

            # Daily loss check
            daily_pnl = getattr(risk_controller, "_daily_pnl", None)
            if daily_pnl is not None and float(daily_pnl) < 0:
                loss_usd = abs(float(daily_pnl))
                signals.append(KalshiRiskSignal(
                    category=RiskEventCategory.LOSS_CAP.value,
                    severity="warning" if loss_usd < 500 else "critical",
                    title="Daily loss alert",
                    detail=f"Daily loss ${loss_usd:.2f}",
                    daily_loss_usd=loss_usd,
                    timestamp=now,
                ))

        except Exception as exc:
            logger.warning(f"Risk signal generation failed: {exc}")

        return signals

    # ── Helpers ────────────────────────────────────────────────────────

    def _extract_asset(self, ticker: str) -> str:
        """Extract asset symbol from Kalshi ticker.

        Uses ``config.crypto_universe.CRYPTO_ASSETS`` when available,
        falling back to a static set.
        """
        try:
            from config.crypto_universe import CRYPTO_ASSETS
            valid_assets = CRYPTO_ASSETS
        except ImportError:
            valid_assets = frozenset({"BTC", "ETH", "SOL", "DOGE", "XRP"})

        parts = ticker.split("-")
        if parts:
            # Try first segment, then two-letter prefix matches
            candidate = parts[0].upper()
            if candidate in valid_assets:
                return candidate
            # Check if ticker starts with any known asset (e.g. "KXBTC…")
            for asset in valid_assets:
                if candidate.endswith(asset):
                    return asset
        return "UNKNOWN"

    def _extract_timeframe(self, ticker: str) -> str:
        """Extract timeframe from Kalshi ticker."""
        ticker_lower = ticker.lower()
        if "24h" in ticker_lower or "daily" in ticker_lower:
            return "24h"
        if "weekly" in ticker_lower or "week" in ticker_lower:
            return "weekly"
        if "monthly" in ticker_lower or "month" in ticker_lower:
            return "monthly"
        if "hourly" in ticker_lower or "1h" in ticker_lower:
            return "1h"
        if "15m" in ticker_lower:
            return "15m"
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
