"""Real data wiring — connect canonical agents to live venue APIs.

Provides concrete _execute() overrides that call:
- KalshiVenueClient for PredictionMarketAgentV2
- ccxt (Binance/Coinbase/Kraken) for CryptoSignalsAgent
- Alpaca REST for MarketResearchAgent equity data

Each wired agent gracefully degrades to empty results when APIs are
unavailable (no keys, network down, circuit open).
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional

from merid.agents.base import AgentCategory, AgentOutput
from merid.agents.research import (
    CryptoSignalsAgent,
    MarketResearchAgent,
    PredictionMarketAgentV2,
    ResearchThesis,
    ThesisDirection,
)
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
        """Lazy-init Kalshi client."""
        if self._client is None:
            try:
                from merid.event_venues.kalshi.client import KalshiVenueClient
                self._client = KalshiVenueClient()
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
            except Exception:
                pass

        return opportunities


# ======================================================================
# Wired CryptoSignalsAgent — ccxt live data
# ======================================================================

class WiredCryptoSignalsAgent(CryptoSignalsAgent):
    """CryptoSignalsAgent wired to ccxt for Binance/Coinbase/Kraken.

    Fetches live tickers and order books, computes cross-exchange
    spreads, and flags structural signals.
    """

    def __init__(self, agent_id: str = "crypto-signals-live"):
        super().__init__(agent_id=agent_id)
        self._exchanges: Dict[str, Any] = {}

    def _init_exchanges(self) -> Dict[str, Any]:
        """Lazy-init ccxt exchanges."""
        if self._exchanges:
            return self._exchanges

        try:
            import ccxt  # type: ignore
        except ImportError:
            logger.warning("ccxt not installed — crypto signals will be empty")
            return {}

        configs = {
            "binance": {
                "cls": "binanceus",
                "key_env": "BINANCE_API_KEY",
                "secret_env": "BINANCE_API_SECRET",
            },
            "coinbase": {
                "cls": "coinbasepro",
                "key_env": "MERID_COINBASE_API_KEY",
                "secret_env": "MERID_COINBASE_API_SECRET",
            },
            "kraken": {
                "cls": "kraken",
                "key_env": "KRAKEN_API_KEY",
                "secret_env": "KRAKEN_PRIVATE_KEY",
            },
        }

        for venue, cfg in configs.items():
            try:
                exchange_cls = getattr(ccxt, cfg["cls"])
                key = os.getenv(cfg["key_env"], "")
                secret = os.getenv(cfg["secret_env"], "")
                ex = exchange_cls({
                    "apiKey": key, "secret": secret,
                    "enableRateLimit": True,
                })
                self._exchanges[venue] = ex
            except Exception as exc:
                logger.warning(f"ccxt init failed for {venue}: {exc}")

        return self._exchanges

    async def _detect_signals(self, context: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Fetch live tickers and compute cross-exchange spreads."""
        exchanges = self._init_exchanges()
        if not exchanges:
            return []

        signals = []
        for pair in self._watched_pairs:
            ccxt_symbol = pair.replace("-", "/")
            tickers: Dict[str, Dict] = {}

            for venue, ex in exchanges.items():
                try:
                    import asyncio
                    ticker = await asyncio.to_thread(ex.fetch_ticker, ccxt_symbol)
                    tickers[venue] = {
                        "bid": ticker.get("bid"),
                        "ask": ticker.get("ask"),
                        "last": ticker.get("last"),
                        "volume": ticker.get("baseVolume"),
                    }
                except Exception as exc:
                    logger.debug(f"Ticker fetch failed {venue}/{pair}: {exc}")

            # Compute cross-exchange spreads
            if len(tickers) >= 2:
                venues = list(tickers.keys())
                for i in range(len(venues)):
                    for j in range(i + 1, len(venues)):
                        v1, v2 = venues[i], venues[j]
                        t1, t2 = tickers[v1], tickers[v2]
                        if t1.get("bid") and t2.get("ask") and t1["bid"] > 0:
                            spread_pct = (t1["bid"] - t2["ask"]) / t2["ask"]
                            if abs(spread_pct) > 0.001:
                                signals.append({
                                    "signal_type": "cross_exchange_spread",
                                    "pair": pair,
                                    "venue_a": v1, "venue_b": v2,
                                    "bid_a": t1["bid"], "ask_b": t2["ask"],
                                    "spread_pct": round(spread_pct, 6),
                                    "source": "ccxt_live",
                                })

            # Flag high volume
            for venue, t in tickers.items():
                if t.get("volume") and t["volume"] > 0:
                    signals.append({
                        "signal_type": "ticker",
                        "pair": pair, "venue": venue,
                        "bid": t.get("bid"), "ask": t.get("ask"),
                        "last": t.get("last"), "volume": t.get("volume"),
                        "source": "ccxt_live",
                    })

        return signals


# ======================================================================
# Wired MarketResearchAgent — Alpaca + Polygon
# ======================================================================

class WiredMarketResearchAgent(MarketResearchAgent):
    """MarketResearchAgent wired to Alpaca for equity data.

    Fetches account snapshots and market data to produce equity theses.
    """

    def __init__(self, agent_id: str = "market-research-live"):
        super().__init__(agent_id=agent_id)
        self._alpaca = None

    def _get_alpaca(self):
        """Lazy-init Alpaca client."""
        if self._alpaca is None:
            try:
                from trading.integrations.alpaca_client import get_alpaca_client
                self._alpaca = get_alpaca_client()
            except Exception as exc:
                logger.warning(f"Alpaca client unavailable: {exc}")
        return self._alpaca

    async def _generate_theses(self, context: Dict[str, Any]) -> List[ResearchThesis]:
        """Fetch Alpaca market data and produce equity theses."""
        client = self._get_alpaca()
        if not client:
            return []

        theses = []
        watchlist = context.get("equity_watchlist", ["AAPL", "TSLA", "SPY", "NVDA", "MSFT"])

        for symbol in watchlist:
            try:
                import asyncio
                bars = await asyncio.to_thread(
                    client.get_bars, symbol, "1Day", limit=5
                )
                bar_list = list(bars)
                if len(bar_list) < 2:
                    continue

                latest = bar_list[-1]
                prev = bar_list[-2]
                change_pct = (latest.c - prev.c) / prev.c if prev.c else 0

                direction = ThesisDirection.NEUTRAL
                if change_pct > 0.02:
                    direction = ThesisDirection.LONG
                elif change_pct < -0.02:
                    direction = ThesisDirection.SHORT

                theses.append(ResearchThesis(
                    thesis_id=f"eq-{symbol}-{datetime.now(timezone.utc).strftime('%Y%m%d')}",
                    domain="equity",
                    instrument=symbol,
                    direction=direction,
                    confidence=min(0.9, 0.5 + abs(change_pct) * 5),
                    drivers=[f"5d_change={change_pct:.4f}", f"volume={latest.v}"],
                    data_sources=["alpaca"],
                    summary=f"{symbol}: {change_pct:+.2%} over 5 days, vol={latest.v}",
                ))
            except Exception as exc:
                logger.debug(f"Alpaca data fetch failed for {symbol}: {exc}")

        return theses
