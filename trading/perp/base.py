"""Shared dataclasses and abstractions for perpetual venue adapters."""

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
    # Deterministic mocks
    # ------------------------------------------------------------------ #
    def _mock_markets(self, limit: int) -> List[PerpMarketSnapshot]:
        random.seed(f"{self.venue}-markets")
        markets: List[PerpMarketSnapshot] = []
        for idx in range(limit):
            symbol = f"{self.venue.upper()}-MOCK-{idx}"
            index_price = random.uniform(1000, 40000)
            price = index_price * random.uniform(0.995, 1.005)
            funding_rate = random.uniform(-0.0008, 0.0008)
            markets.append(
                PerpMarketSnapshot(
                    venue=self.venue,
                    symbol=symbol,
                    price=price,
                    index_price=index_price,
                    open_interest=random.uniform(1e5, 5e6),
                    funding_rate=funding_rate,
                    volume_24h=random.uniform(5e6, 5e8),
                    basis=price - index_price,
                    metadata={"mock": True},
                )
            )
        return markets

    def _mock_funding(self, symbols: Optional[List[str]]) -> List[FundingRateSnapshot]:
        random.seed(f"{self.venue}-funding")
        symbols = symbols or [f"{self.venue.upper()}-MOCK-{idx}" for idx in range(5)]
        now_ms = time.time() * 1000
        snapshots: List[FundingRateSnapshot] = []
        for symbol in symbols:
            funding_rate = random.uniform(-0.0009, 0.0009)
            settlement_ms = now_ms + random.uniform(30, 180) * 60 * 1000
            apr = funding_rate * 24 * 365
            snapshots.append(
                FundingRateSnapshot(
                    venue=self.venue,
                    symbol=symbol,
                    funding_rate=funding_rate,
                    next_settlement_ms=settlement_ms,
                    estimated_apr=apr,
                    metadata={"mock": True},
                )
            )
        return snapshots

    def _mock_whales(self, limit: int) -> List[WhaleSignal]:
        random.seed(f"{self.venue}-whales")
        signals: List[WhaleSignal] = []
        for _ in range(limit):
            symbol = f"{self.venue.upper()}-MOCK-{random.randint(1,5)}"
            direction = random.choice(["buy", "sell"])
            notional = random.uniform(1e5, 5e6)
            timestamp_ms = time.time() * 1000 - random.uniform(0, 15) * 60 * 1000
            signals.append(
                WhaleSignal(
                    venue=self.venue,
                    symbol=symbol,
                    direction=direction,
                    notional=notional,
                    timestamp_ms=timestamp_ms,
                    source="mock",
                    metadata={"mock": True},
                )
            )
        return signals
