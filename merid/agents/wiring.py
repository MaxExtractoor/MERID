"""Real data wiring — connect canonical agents to live venue APIs.

Provides concrete _execute() overrides that call:
- KalshiVenueClient for PredictionMarketAgentV2

Each wired agent gracefully degrades to empty results when APIs are
unavailable (no keys, network down, circuit open).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict, List, Optional

from merid.agents.base import AgentOutput
from merid.agents.research import PredictionMarketAgentV2
from merid.prediction.model import PredictionMarketModel

from utils.logger import get_logger

logger = get_logger("merid.agents.wiring")


# ======================================================================
# Wired PredictionMarketAgent — Kalshi live data
# ======================================================================

class WiredPredictionMarketAgent(PredictionMarketAgentV2):
    """PredictionMarketAgentV2 wired to KalshiVenueClient.

    Fetches live markets, runs PredictionMarketModel for edge detection,
    and produces structured opportunity objects.
    """

    def __init__(self, agent_id: str = "pm-research-live"):
        super().__init__(agent_id=agent_id, venue="kalshi")
        self._client = None
        self._model = PredictionMarketModel()

    def _get_client(self):
        """Lazy-init Kalshi client — uses the process-wide singleton."""
        if self._client is None:
            try:
                from merid.event_venues.kalshi.client import get_kalshi_client
                self._client = get_kalshi_client()
            except Exception as exc:
                logger.warning(f"KalshiVenueClient unavailable: {exc}")
        return self._client

    async def _scan_opportunities(self, context: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Fetch live Kalshi markets and detect mispricing."""
        client = self._get_client()
        if not client:
            return []

        opportunities = []
        try:
            await client.connect()
            markets = await client.list_markets()

            for market in markets[:50]:  # Cap to avoid rate limits
                try:
                    orderbook = await client.get_orderbook(market.market_id)
                    if not orderbook:
                        continue

                    # Build snapshot and check for arb / edge
                    yes_ask = orderbook.asks[0].price if orderbook.asks else None
                    no_ask = None  # Would need no-side orderbook
                    yes_bid = orderbook.bids[0].price if orderbook.bids else None

                    if yes_ask is not None and yes_bid is not None:
                        spread = yes_ask - yes_bid
                        implied_prob = self._model.implied_probability(int(yes_ask * 100))

                        if spread < 0.05 and implied_prob > 0:
                            opportunities.append({
                                "market_id": market.market_id,
                                "title": getattr(market, "title", market.market_id),
                                "yes_ask": float(yes_ask),
                                "yes_bid": float(yes_bid),
                                "spread": float(spread),
                                "implied_prob": float(implied_prob),
                                "source": "kalshi_live",
                            })
                except Exception as exc:
                    logger.debug(f"Skipping market {market.market_id}: {exc}")

        except Exception as exc:
            logger.warning(f"Kalshi scan failed: {exc}")
        finally:
            try:
                await client.close()
            except Exception as exc:
                logger.debug("async_op_suppressed", error=str(exc))

        return opportunities

