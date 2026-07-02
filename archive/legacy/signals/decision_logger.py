"""
Trade Decision Logger
=====================
Structured audit logging for all TA-driven trading decisions.
Produces immutable decision records for backtesting, debugging, and compliance.
"""

from __future__ import annotations

import json
import time
import uuid
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field

from utils.logger import get_logger
from .ta_models import FusedClusterSignal, MarketStructure

logger = get_logger("merid.signals.decision_logger")


@dataclass
class TradeDecisionLog:
    """
    Immutable record of a trade decision and its context.

    This is the audit trail for every Kalshi trade attempt, whether
    accepted or rejected. Enables post-trade analysis and model iteration.
    """
    # Identifiers
    decision_id: str
    timestamp: float
    asset: str
    timeframe: str

    # Market context at decision time
    spot: float
    trend_regime: str
    vol_regime: str
    liquidity_regime: str

    # Signal context
    cluster_direction: str
    cluster_quality: float
    cluster_confidence: float
    rationale_tags: List[str]
    higher_tf_alignment: float
    lower_tf_confirmation: float

    # Kalshi contract selection
    selected_ticker: Optional[str]
    strike: Optional[float]
    distance_pct: Optional[float]
    base_max_distance_pct: float
    dynamic_max_distance_pct: float
    rejection_reason: Optional[str]

    # Sizing
    base_size: int
    adjusted_size: int
    size_multiplier: float
    risk_usd: float

    # Invariants checked
    signal_valid: bool
    regime_valid: bool
    distance_valid: bool
    risk_gate_passed: bool

    # Optional notes
    notes: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "decision_id": self.decision_id,
            "timestamp": self.timestamp,
            "iso_time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(self.timestamp)),
            "asset": self.asset,
            "timeframe": self.timeframe,
            "spot": round(self.spot, 2),
            "trend_regime": self.trend_regime,
            "vol_regime": self.vol_regime,
            "liquidity_regime": self.liquidity_regime,
            "cluster": {
                "direction": self.cluster_direction,
                "quality": round(self.cluster_quality, 3),
                "confidence": round(self.cluster_confidence, 3),
                "tags": self.rationale_tags,
                "alignment": round(self.higher_tf_alignment, 3),
                "confirmation": round(self.lower_tf_confirmation, 3),
            },
            "kalshi_selection": {
                "ticker": self.selected_ticker,
                "strike": round(self.strike, 2) if self.strike else None,
                "distance_pct": round(self.distance_pct, 4) if self.distance_pct else None,
                "base_max_pct": round(self.base_max_distance_pct, 4),
                "dyn_max_pct": round(self.dynamic_max_distance_pct, 4),
                "rejection": self.rejection_reason,
            },
            "sizing": {
                "base_size": self.base_size,
                "adjusted_size": self.adjusted_size,
                "multiplier": round(self.size_multiplier, 3),
                "risk_usd": round(self.risk_usd, 2),
            },
            "invariants": {
                "signal_valid": self.signal_valid,
                "regime_valid": self.regime_valid,
                "distance_valid": self.distance_valid,
                "risk_gate_passed": self.risk_gate_passed,
            },
            "notes": self.notes,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), default=str, sort_keys=True)


class DecisionLogger:
    """
    Central logging facility for trade decisions.

    Writes structured logs to both file (via structlog) and in-memory
    ring buffer for dashboard access.
    """

    def __init__(self, max_buffer_size: int = 10000):
        self._buffer: List[TradeDecisionLog] = []
        self._max_buffer = max_buffer_size

    def log_decision(self, log: TradeDecisionLog) -> None:
        """Log a trade decision."""
        # Add to buffer
        self._buffer.append(log)
        if len(self._buffer) > self._max_buffer:
            self._buffer.pop(0)

        # Log to structured logger
        logger.info(
            "[TRADE_DECISION] %s",
            log.to_json(),
            extra={
                "decision_id": log.decision_id,
                "asset": log.asset,
                "direction": log.cluster_direction,
                "rejected": log.rejection_reason is not None,
            }
        )

    def create_from_fused_signal(
        self,
        asset: str,
        timeframe: str,
        spot: float,
        fused_signal: FusedClusterSignal,
        market_structure: MarketStructure,
        ticker: Optional[str],
        strike: Optional[float],
        base_max_distance: float,
        dynamic_max_distance: float,
        rejection: Optional[str],
        base_size: int,
        risk_usd: float,
    ) -> TradeDecisionLog:
        """Convenience factory to create decision log from signal context."""

        # Check invariants
        signal_valid = fused_signal.is_tradeable()
        regime_valid = market_structure.trend_regime != "chop" or fused_signal.quality_score > 0.6

        distance_pct = None
        if spot and strike and strike > 0:
            distance_pct = abs(spot - strike) / strike

        distance_valid = distance_pct is not None and distance_pct <= dynamic_max_distance

        # Calculate adjusted size
        size_mult = fused_signal.size_multiplier if fused_signal.size_multiplier > 0 else 1.0
        adjusted_size = int(base_size * size_mult)

        return TradeDecisionLog(
            decision_id=str(uuid.uuid4())[:8],
            timestamp=time.time(),
            asset=asset,
            timeframe=timeframe,
            spot=spot,
            trend_regime=market_structure.trend_regime,
            vol_regime=market_structure.vol_regime,
            liquidity_regime=market_structure.liquidity_regime,
            cluster_direction=fused_signal.direction,
            cluster_quality=fused_signal.quality_score,
            cluster_confidence=fused_signal.confidence,
            rationale_tags=fused_signal.rationale_tags,
            higher_tf_alignment=fused_signal.higher_tf_alignment,
            lower_tf_confirmation=fused_signal.lower_tf_confirmation,
            selected_ticker=ticker,
            strike=strike,
            distance_pct=distance_pct,
            base_max_distance_pct=base_max_distance,
            dynamic_max_distance_pct=dynamic_max_distance,
            rejection_reason=rejection or fused_signal.rejection_reason,
            base_size=base_size,
            adjusted_size=adjusted_size,
            size_multiplier=size_mult,
            risk_usd=risk_usd,
            signal_valid=signal_valid,
            regime_valid=regime_valid,
            distance_valid=distance_valid,
            risk_gate_passed=risk_usd > 0,
        )

    def get_recent_decisions(
        self,
        asset: Optional[str] = None,
        n: int = 100,
    ) -> List[Dict[str, Any]]:
        """Get recent decisions (for dashboard)."""
        recent = self._buffer[-n:]
        if asset:
            recent = [d for d in recent if d.asset == asset]
        return [d.to_dict() for d in recent]

    def get_stats(self, window: int = 1000) -> Dict[str, Any]:
        """Get decision statistics (for dashboard)."""
        recent = self._buffer[-window:]
        if not recent:
            return {"total": 0}

        total = len(recent)
        accepted = sum(1 for d in recent if d.rejection_reason is None)
        by_asset: Dict[str, int] = {}
        by_rejection: Dict[str, int] = {}

        for d in recent:
            by_asset[d.asset] = by_asset.get(d.asset, 0) + 1
            if d.rejection_reason:
                by_rejection[d.rejection_reason] = by_rejection.get(d.rejection_reason, 0) + 1

        return {
            "total": total,
            "accepted": accepted,
            "rejected": total - accepted,
            "accept_rate": round(accepted / total, 3),
            "by_asset": by_asset,
            "by_rejection_reason": by_rejection,
        }


# Global singleton
decision_logger = DecisionLogger()


def get_decision_logger() -> DecisionLogger:
    """Get the global decision logger."""
    return decision_logger
