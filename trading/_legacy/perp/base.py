"""
PerpVenueAdapterBase — Base class for perpetual market adapters.

Provides common functionality for all perpetual market adapters including
market data fetching, funding rate tracking, and whale signal detection.
"""

# LEGACY EXECUTION GUARD: This module contains legacy execution logic
# To enable, set MERID_ALLOW_LEGACY_EXECUTION=true (non-prod environments only)
# Production deployments must never set this env var
import os
if os.getenv("MERID_ALLOW_LEGACY_EXECUTION", "false").lower() != "true":
    raise RuntimeError(
        "Legacy execution module cannot be imported in production. "
        "Set MERID_ALLOW_LEGACY_EXECUTION=true only in non-prod environments."
    )

from __future__ import annotations

import os
import random
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Protocol

import httpx

from utils.logger import get_logger

logger = get_logger("trading.perp.base")


@dataclass(frozen=True)
class PerpMarketSnapshot:
    venue: str
    symbol: str
    price: float
    index_price: float
    open_interest: float
    funding_rate: float
    volume_24h: float
    basis: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class FundingRateSnapshot:
    venue: str
    symbol: str
    funding_rate: float
    next_settlement_ms: float
    estimated_apr: float
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class WhaleSignal:
    venue: str
    symbol: str
    direction: str
    notional: float
    timestamp_ms: float
    source: str
    metadata: Dict[str, Any] = field(default_factory=dict)


class PerpVenueAdapter(Protocol):
    venue: str

    def fetch_markets(self, limit: int = 50) -> List[PerpMarketSnapshot]:
        ...

    def fetch_funding_rates(self, symbols: Optional[List[str]] = None) -> List[FundingRateSnapshot]:
        ...

    def fetch_whale_signals(self, limit: int = 10) -> List[WhaleSignal]:
        ...


class PerpVenueAdapterBase(PerpVenueAdapter):
    """Reusable base class providing HTTP client + deterministic mocks."""

    venue: str = "perp"
    live_markets_endpoint: Optional[str] = None
    live_funding_endpoint: Optional[str] = None
    live_whales_endpoint: Optional[str] = None

    def __init__(
        self,
        *,
        api_key: Optional[str] = None,
        api_secret: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout: float = 10.0,
        use_mock: bool = False,
    ) -> None:
        self.api_key = api_key or os.getenv(f"MERID_{self.venue.upper()}_API_KEY")
        self.api_secret = api_secret or os.getenv(f"MERID_{self.venue.upper()}_API_SECRET")
        self.base_url = base_url or os.getenv(f"MERID_{self.venue.upper()}_BASE_URL")
        self.use_mock = use_mock or not self.api_key
        self._client = httpx.Client(timeout=timeout)

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #
    def fetch_markets(self, limit: int = 50) -> List[PerpMarketSnapshot]:
        if self.use_mock:
            return self._mock_markets(limit)
        try:
            markets = self._fetch_markets_live(limit)
            if markets:
                return markets
        except Exception as exc:
            logger.warning("Live market fetch failed for %s: %s", self.venue, exc)
        return self._mock_markets(limit)

    def fetch_funding_rates(self, symbols: Optional[List[str]] = None) -> List[FundingRateSnapshot]:
        if self.use_mock:
            return self._mock_funding(symbols)
        try:
            data = self._fetch_funding_live(symbols)
            if data:
                return data
        except Exception as exc:
            logger.warning("Live funding fetch failed for %s: %s", self.venue, exc)
        return self._mock_funding(symbols)

    def fetch_whale_signals(self, limit: int = 10) -> List[WhaleSignal]:
        if self.use_mock:
            return self._mock_whales(limit)
        try:
            data = self._fetch_whales_live(limit)
            if data:
                return data
        except Exception as exc:
            logger.debug("Whale feed unavailable for %s: %s", self.venue, exc)
        return self._mock_whales(limit)

    # ------------------------------------------------------------------ #
    # Hooks to override
    # ------------------------------------------------------------------ #
    def _fetch_markets_live(self, limit: int) -> List[PerpMarketSnapshot]:
        raise NotImplementedError

    def _fetch_funding_live(self, symbols: Optional[List[str]]) -> List[FundingRateSnapshot]:
        raise NotImplementedError

    def _fetch_whales_live(self, limit: int) -> List[WhaleSignal]:
        return []

    # ------------------------------------------------------------------ #
    # Fallback methods - return empty when no API key
    # ------------------------------------------------------------------ #
    def _mock_markets(self, limit: int) -> List[PerpMarketSnapshot]:
        """Return empty list when no API key - no fake data."""
        logger.debug("No API key for %s - market data unavailable", self.venue)
        return []

    def _mock_funding(self, symbols: Optional[List[str]]) -> List[FundingRateSnapshot]:
        """Return empty list when no API key - no fake data."""
        logger.debug("No API key for %s - funding data unavailable", self.venue)
        return []

    def _mock_whales(self, limit: int) -> List[WhaleSignal]:
        """Return empty list when no API key - no fake data."""
        logger.debug("No API key for %s - whale data unavailable", self.venue)
        return []
