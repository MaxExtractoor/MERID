"""Augur trading helper layer for MERID hybrid simulations.

This module mirrors the Polymarket trading helper to keep the simulation engine
agnostic of data sources. It fetches market data via The Graph subgraph and
exposes the same negative-risk opportunity scanning helpers plus a simple
trade stub.
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional, Sequence

import httpx


class AugurTradingLayer:
    SUBGRAPH_URL = "https://api.thegraph.com/subgraphs/name/augurproject/augur-v2"

    def __init__(self, *, timeout: float = 12.0, use_mock: bool = False) -> None:
        self._client = httpx.Client(timeout=timeout)
        self.use_mock = use_mock or bool(os.getenv("MERID_AUGUR_MOCK"))

    def fetch_markets(self, *, category: Optional[str] = None, limit: int = 25) -> List[Dict[str, Any]]:
        if self.use_mock:
            return self._mock_markets(limit)

        query = {
            "query": """
            {
              markets(first: %d, orderBy: volume, orderDirection: desc%s) {
                id
                description
                volume
                outcomes {
                  id
                  price
                  payoutNumerators
                }
              }
            }
            """
            % (
                limit,
                f', where: {{ category: "{category}" }}' if category else "",
            )
        }

        try:
            response = self._client.post(self.SUBGRAPH_URL, json=query)
            response.raise_for_status()
            data = response.json()
            markets = data.get("data", {}).get("markets", [])
        except Exception:
            return self._mock_markets(limit)

        normalized: List[Dict[str, Any]] = []
        for market in markets:
            outcomes = market.get("outcomes", []) or []
            yes_price = self._extract_yes_price(outcomes)
            no_price = 1 - yes_price if yes_price is not None else None
            normalized.append(
                {
                    "id": market.get("id"),
                    "description": market.get("description"),
                    "volume": float(market.get("volume") or 0),
                    "yes_price": yes_price if yes_price is not None else 0.5,
                    "no_price": no_price if no_price is not None else 0.5,
                }
            )
        return normalized

    def find_negative_risk_opportunities(
        self,
        markets: Sequence[Dict[str, Any]],
        *,
        min_volume: float = 100.0,
        yes_prob_threshold: float = 0.05,
    ) -> List[Dict[str, Any]]:
        opportunities: List[Dict[str, Any]] = []
        for market in markets:
            if not market:
                continue
            volume = float(market.get("volume", 0))
            if volume < min_volume:
                continue
            yes_price = float(market.get("yes_price") or 0.0)
            no_price = float(market.get("no_price") or (1 - yes_price))
            edge = max(0.0, no_price - (1 - yes_price))
            if edge >= yes_prob_threshold:
                opportunities.append(
                    {
                        "id": market.get("id"),
                        "slug": market.get("description", "augur-market"),
                        "volume": volume,
                        "yes_price": yes_price,
                        "no_price": no_price,
                        "edge": edge,
                        "platform": "augur",
                    }
                )
        return sorted(opportunities, key=lambda item: item["edge"], reverse=True)

    def place_trade(self, market_id: str, outcome: str, amount_eth: float) -> Dict[str, Any]:
        return {
            "status": "queued",
            "market_id": market_id,
            "outcome": outcome,
            "amount_eth": amount_eth,
            "tx_hash": None,
        }

    def _extract_yes_price(self, outcomes: Sequence[Dict[str, Any]]) -> Optional[float]:
        if not outcomes:
            return None
        try:
            best = max(outcomes, key=lambda o: float(o.get("price", 0)))
            return float(best.get("price", 0))
        except Exception:
            return None

    def _mock_markets(self, limit: int) -> List[Dict[str, Any]]:
        return [
            {
                "id": f"mock-augur-{idx}",
                "description": f"Mock Augur Market {idx}",
                "volume": 500 + idx * 25,
                "yes_price": 0.4 + (idx % 5) * 0.05,
                "no_price": 0.6 - (idx % 5) * 0.05,
            }
            for idx in range(limit)
        ]
