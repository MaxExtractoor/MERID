"""Trading helpers for Polymarket data and Chainlink oracle anchoring.

This module centralizes all external market-data wiring so that the simulation
engine can focus on swarm logic. It provides:
  * PolymarketClient — lightweight Gamma API consumer with deterministic mocks
  * ChainlinkOracle — pulls on-network reference feeds (ETH/USD, BTC/USD, etc.)
  * feed_probability helper — maps Chainlink prices into [0, 1] signals
"""

from __future__ import annotations

import os
import random
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence

import httpx

from utils.logger import get_logger

logger = get_logger("trading.polymarket_trading_layer")


@dataclass(frozen=True)
class ChainlinkFeed:
    slug: str
    category: str
    name: str
    scale_hint: float = 1000.0


DEFAULT_CHAINLINK_FEEDS: List[ChainlinkFeed] = [
    ChainlinkFeed(slug="eth-usd", category="crypto-usd", name="ETH/USD", scale_hint=5000.0),
    ChainlinkFeed(slug="btc-usd", category="crypto-usd", name="BTC/USD", scale_hint=80000.0),
    ChainlinkFeed(slug="matic-usd", category="crypto-usd", name="MATIC/USD", scale_hint=5.0),
    ChainlinkFeed(slug="sports-us-election-2024", category="sports", name="US Election 2024", scale_hint=1.0),
]


class ChainlinkOracle:
    """Minimal REST wrapper around Chainlink market data endpoints.

    The official Chainlink Market Data API exposes feeds under the pattern:
    https://cl-market-data.chain.link/api/price-feeds/{network}/{category}/{slug}

    When the upstream API is unreachable we fall back to deterministic mock data
    so that the simulation loop never stalls during offline development.
    """

    BASE_URL = "https://cl-market-data.chain.link/api/price-feeds"

    def __init__(self, *, network: str = "polygon", timeout: float = 8.0) -> None:
        self.network = network
        self._client = httpx.Client(timeout=timeout)

    def fetch_feeds(self, feeds: Sequence[ChainlinkFeed] = DEFAULT_CHAINLINK_FEEDS) -> Dict[str, Dict[str, Any]]:
        snapshots: Dict[str, Dict[str, Any]] = {}
        for feed in feeds:
            url = f"{self.BASE_URL}/{self.network}/{feed.category}/{feed.slug}"
            try:
                response = self._client.get(url)
                response.raise_for_status()
                payload = response.json()
                price = self._extract_price(payload)
                updated_at = self._extract_timestamp(payload)
            except Exception:
                price = self._mock_price(feed.slug)
                updated_at = time.time()
            snapshots[feed.slug] = {
                "name": feed.name,
                "price": price,
                "updated_at": updated_at,
                "source": url,
                "scale_hint": feed.scale_hint,
            }
        return snapshots

    def _extract_price(self, payload: Dict[str, Any]) -> float:
        if isinstance(payload, dict):
            if "price" in payload:
                return float(payload["price"])
            data = payload.get("data") or payload.get("value") or {}
            if isinstance(data, dict):
                if "price" in data:
                    return float(data["price"])
                if "result" in data:
                    return float(data["result"])
        raise ValueError("Unsupported Chainlink price payload")

    def _extract_timestamp(self, payload: Dict[str, Any]) -> float:
        if isinstance(payload, dict):
            for key in ("updatedAt", "timestamp", "updated_at"):
                if key in payload:
                    return float(payload[key])
            data = payload.get("data")
            if isinstance(data, dict):
                for key in ("timestamp", "updated_at"):
                    if key in data:
                        return float(data[key])
        return time.time()

    def _mock_price(self, slug: str) -> float:
        """Return 0 when no live price - no fake data."""
        logger.debug("No live price for %s", slug)
        return 0.0


def feed_probability(feed_snapshot: Dict[str, Any]) -> float:
    """Map an absolute Chainlink price to a bounded probability signal.

    The heuristic uses the configured scale_hint to normalize the price into the
    [0, 1] interval. This keeps downstream logic deterministic even when the raw
    prices span several orders of magnitude.
    """

    price = float(feed_snapshot.get("price", 0.0))
    scale = float(feed_snapshot.get("scale_hint", 1.0)) or 1.0
    return max(0.0, min(1.0, price / scale))


class PolymarketClient:
    """Minimal Gamma API consumer with optional mock mode."""

    MARKETS_ENDPOINT = "https://gamma-api.polymarket.com/markets"

    def __init__(self, *, timeout: float = 10.0, use_mock: bool = False) -> None:
        self.timeout = timeout
        self.use_mock = use_mock or bool(os.getenv("MERID_POLYMARKET_MOCK"))
        self._client = httpx.Client(timeout=timeout)

    def fetch_markets(self, *, category: Optional[str] = None, limit: int = 25) -> List[Dict[str, Any]]:
        if self.use_mock:
            return self._mock_markets(limit)

        params = {"active": "true", "limit": limit}
        if category:
            params["category"] = category

        try:
            response = self._client.get(self.MARKETS_ENDPOINT, params=params)
            response.raise_for_status()
            markets = response.json()
        except Exception:
            return self._mock_markets(limit)

        if isinstance(markets, dict) and "data" in markets:
            return markets["data"][:limit]
        if isinstance(markets, list):
            return markets[:limit]
        return []

    def find_negative_risk_opportunities(
        self,
        markets: Sequence[Dict[str, Any]],
        *,
        min_volume: float = 500.0,
        yes_prob_threshold: float = 0.05,
    ) -> List[Dict[str, Any]]:
        opportunities: List[Dict[str, Any]] = []
        for market in markets:
            if not market:
                continue
            slug = market.get("slug") or market.get("question") or "unknown"
            volume = float(market.get("volume", 0))
            yes_price = float(market.get("yesPrice") or market.get("yes_price") or 0.0)
            no_price = float(market.get("noPrice") or market.get("no_price") or (1 - yes_price))

            if volume < min_volume:
                continue
            edge = max(0.0, no_price - (1 - yes_price))
            if edge >= yes_prob_threshold:
                opportunities.append(
                    {
                        "slug": slug,
                        "volume": volume,
                        "yes_price": yes_price,
                        "no_price": no_price,
                        "edge": edge,
                        "platform": "polymarket",
                    }
                )

        return sorted(opportunities, key=lambda item: item["edge"], reverse=True)

    def _mock_markets(self, limit: int) -> List[Dict[str, Any]]:
        """Return empty list when API unavailable - no fake data."""
        logger.debug("Polymarket API unavailable - returning empty list")
        return []
