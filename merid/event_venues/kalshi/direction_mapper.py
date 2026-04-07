"""Direction Mapper — Centralized forecast-to-side conversion for strategies.

Provides a single, testable utility for converting model forecasts (numeric signals,
probabilities, or directional labels) into Kalshi YES/NO sides, accounting for the
market's direction (up vs down).

Usage::

    from merid.event_venues.kalshi.direction_mapper import DirectionMapper

    mapper = DirectionMapper()

    # Convert numeric signal to side
    side = mapper.forecast_to_side(
        forecast_signal=0.05,  # positive = bullish
        market_direction="up"
    )  # "yes"

    # Validate consistency
    is_valid = mapper.validate_direction_consistency(
        asset="BTC",
        timeframe="15m",
        strategy_name="momentum",
        forecast_signal=0.05,
        chosen_side="yes",
        market_direction="up"
    )  # True
"""

from __future__ import annotations

from typing import Optional

from merid.event_venues.kalshi.direction_semantics import determine_kalshi_side
from utils.logger import get_logger

logger = get_logger("merid.event_venues.kalshi.direction_mapper")


class DirectionMapper:
    """Maps strategy forecasts to Kalshi YES/NO sides consistently.

    Ensures all strategies use the same logic for converting forecasts into
    trading decisions, preventing sign errors and direction mismatches.
    """

    def forecast_to_side(
        self,
        forecast_signal: float,
        market_direction: str,
    ) -> str:
        """Convert numeric forecast signal to Kalshi side.

        Args:
            forecast_signal: Signed forecast value.
                Positive values indicate bullish (price up expected).
                Negative values indicate bearish (price down expected).
            market_direction: Market direction from Kalshi ("up" or "down").

        Returns:
            "yes" or "no"

        Examples:
            >>> mapper = DirectionMapper()
            >>> mapper.forecast_to_side(0.05, "up")
            'yes'

            >>> mapper.forecast_to_side(-0.03, "up")
            'no'

            >>> mapper.forecast_to_side(0.05, "down")
            'no'

            >>> mapper.forecast_to_side(-0.03, "down")
            'yes'
        """
        forecast_direction = "bullish" if forecast_signal >= 0 else "bearish"
        return determine_kalshi_side(forecast_direction, market_direction)

    def validate_direction_consistency(
        self,
        asset: str,
        timeframe: str,
        strategy_name: str,
        forecast_signal: float,
        chosen_side: str,
        market_direction: str,
    ) -> bool:
        """Validate that chosen_side matches forecast_signal + market_direction.

        Logs an ERROR if a mismatch is detected, indicating a potential bug
        in the strategy implementation.

        Args:
            asset: Asset symbol (e.g., "BTC").
            timeframe: Timeframe (e.g., "15m").
            strategy_name: Name of the strategy generating the forecast.
            forecast_signal: Numeric forecast value (positive = bullish).
            chosen_side: The side the strategy chose ("yes" or "no").
            market_direction: Market direction ("up" or "down").

        Returns:
            True if consistent, False if mismatch detected.
        """
        expected_side = self.forecast_to_side(forecast_signal, market_direction)

        if chosen_side != expected_side:
            logger.error(
                "DIRECTION MISMATCH: %s/%s strategy=%s forecast_signal=%.4f "
                "market_direction=%s expected_side=%s chosen_side=%s",
                asset, timeframe, strategy_name, forecast_signal,
                market_direction, expected_side, chosen_side
            )
            return False

        logger.debug(
            "Direction consistent: %s/%s strategy=%s signal=%.4f market=%s side=%s",
            asset, timeframe, strategy_name, forecast_signal,
            market_direction, chosen_side
        )
        return True


# Module-level singleton
_mapper: Optional[DirectionMapper] = None


def get_direction_mapper() -> DirectionMapper:
    """Get or create the singleton DirectionMapper instance."""
    global _mapper
    if _mapper is None:
        _mapper = DirectionMapper()
    return _mapper
