"""Canonical sentiment record for lane → swarm → sizing pipelines.

Use with :data:`config.kalshi_crypto_config.ACTIVE_CRYPTO_ASSETS` and
:data:`ACTIVE_CRYPTO_WS_TIMEFRAMES` / mood labels — do not hard-code BTC-only lists.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Optional


@dataclass
class SentimentSignal:
    """Normalized sentiment observation for one crypto asset and timeframe."""

    asset: str
    timeframe: str
    score: float
    intensity: float
    source: str
    generated_at: datetime
    window_start: Optional[datetime] = None
    window_end: Optional[datetime] = None
    market_ticker: Optional[str] = None
    confidence: float = 0.5
    trace_id: Optional[str] = None
    extra: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "asset": self.asset,
            "timeframe": self.timeframe,
            "score": self.score,
            "intensity": self.intensity,
            "source": self.source,
            "generated_at": self.generated_at.isoformat(),
            "window_start": self.window_start.isoformat() if self.window_start else None,
            "window_end": self.window_end.isoformat() if self.window_end else None,
            "market_ticker": self.market_ticker,
            "confidence": self.confidence,
            "trace_id": self.trace_id,
            **self.extra,
        }


def utcnow() -> datetime:
    return datetime.now(timezone.utc)
