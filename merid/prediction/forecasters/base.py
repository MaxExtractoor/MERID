"""Base forecaster interface and shared types.

Every forecaster must implement ``predict()`` returning a ``ForecastResult``.
The ``forecaster_id`` property uniquely identifies it for CalibrationStore tracking.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass
class ForecastResult:
    """Output of a single forecaster's prediction."""
    forecaster_id: str
    p_model: float          # YES probability (0.0–1.0)
    confidence: float       # signal confidence (0.0–1.0)
    components: Dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "forecaster_id": self.forecaster_id,
            "p_model": round(self.p_model, 6),
            "confidence": round(self.confidence, 4),
            "components": {k: round(v, 6) for k, v in self.components.items()},
        }


class Forecaster(ABC):
    """Abstract base class for all forecasters."""

    @property
    @abstractmethod
    def forecaster_id(self) -> str:
        """Unique identifier for this forecaster (used in CalibrationStore)."""
        ...

    @abstractmethod
    def predict(
        self,
        market_id: str,
        implied_yes: float,
        implied_no: float,
        volume: float,
        open_interest: float,
        minutes_to_expiry: Optional[float],
        asset: Optional[str] = None,
        timeframe: Optional[str] = None,
        bid: Optional[float] = None,
        ask: Optional[float] = None,
        category: Optional[str] = None,
        **kwargs,
    ) -> Optional[ForecastResult]:
        """Produce a YES probability estimate for a Kalshi market.

        Args:
            market_id: Kalshi market ticker.
            implied_yes: Market-implied YES probability (0–1).
            implied_no: Market-implied NO probability (0–1).
            volume: Trading volume.
            open_interest: Open interest.
            minutes_to_expiry: Minutes until contract expiry.
            asset: Underlying asset (BTC, ETH, etc.).
            timeframe: Market timeframe (15m, 1h, daily).
            bid: Best bid price (0–1).
            ask: Best ask price (0–1).
            category: Market category (crypto, macro, etc.).

        Returns:
            ForecastResult or None if the model can't produce a prediction.
        """
        ...
