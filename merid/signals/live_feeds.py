"""§4 Live data feeds — wire real APIs into the signal layer feature services.

Fetches from:
  - Finnhub: market news + sentiment (FINNHUB_API_KEY)
  - FRED: macro economic indicators (free, no key required for basic series)
  - CoinGecko: on-chain / crypto market data (free tier, no key)
  - Polygon: news sentiment as fallback (POLYGON_API_KEY)

Each fetcher calls `.ingest()` on the corresponding FeatureService,
so the existing decay math and feature aggregation remain untouched.

Usage:
    from merid.signals.live_feeds import LiveFeedManager
    mgr = LiveFeedManager(feature_service)
    await mgr.refresh_all(["BTC", "ETH", "AAPL"])
"""

from __future__ import annotations

import os
import time
from typing import Any, Dict, List, Optional

import httpx

from utils.logger import get_logger

logger = get_logger("merid.signals.live_feeds")

# Timeouts and rate limiting
_HTTP_TIMEOUT = 10.0
_MIN_FETCH_INTERVAL = 30.0  # Don't re-fetch more often than every 30s


class LiveFeedManager:
    """Orchestrates live data fetching and ingestion into feature services."""

    def __init__(self, feature_service=None):
        if feature_service is None:
            from merid.signals.features import get_feature_service
            feature_service = self._fs = get_feature_service()
        else:
            self._fs = feature_service

        self._finnhub_key = os.getenv("FINNHUB_API_KEY", "")
        self._polygon_key = os.getenv("POLYGON_API_KEY", "")
        self._last_fetch: Dict[str, float] = {}  # feed_name → last_fetch_ts
        self._client = httpx.AsyncClient(timeout=_HTTP_TIMEOUT)
        self._stats: Dict[str, int] = {
            "news_fetched": 0,
            "macro_fetched": 0,
            "onchain_fetched": 0,
            "errors": 0,
        }

    # ── Public API ────────────────────────────────────────────────────

    async def refresh_all(self, symbols: List[str], now: Optional[float] = None):
        """Refresh all feeds for the given symbols."""
        now = now or time.time()
        await self.refresh_news(symbols, now)
        await self.refresh_macro(now)
        await self.refresh_onchain(symbols, now)

    async def refresh_news(self, symbols: List[str], now: Optional[float] = None):
        """Fetch latest news from Finnhub and/or Polygon."""
        now = now or time.time()
        if not self._should_fetch("news", now):
            return

        if self._finnhub_key:
            await self._fetch_finnhub_news(symbols, now)
        elif self._polygon_key:
            await self._fetch_polygon_news(symbols, now)
        else:
            logger.debug("No news API key configured — using synthetic fallback")

        self._last_fetch["news"] = now

    async def refresh_macro(self, now: Optional[float] = None):
        """Fetch macro indicators from FRED."""
        now = now or time.time()
        if not self._should_fetch("macro", now):
            return

        await self._fetch_fred_macro(now)
        self._last_fetch["macro"] = now

    async def refresh_onchain(self, symbols: List[str], now: Optional[float] = None):
        """Fetch on-chain / crypto data from CoinGecko."""
        now = now or time.time()
        if not self._should_fetch("onchain", now):
            return

        await self._fetch_coingecko(symbols, now)
        self._last_fetch["onchain"] = now

    def stats(self) -> Dict[str, int]:
        return dict(self._stats)

    def status(self) -> Dict[str, Any]:
        """Full status for API exposure."""
        return {
            "finnhub_configured": bool(self._finnhub_key),
            "polygon_configured": bool(self._polygon_key),
            "last_fetch": {k: round(v, 1) for k, v in self._last_fetch.items()},
            "stats": self.stats(),
        }

    async def close(self):
        await self._client.aclose()

    # ── Finnhub news ──────────────────────────────────────────────────

    async def _fetch_finnhub_news(self, symbols: List[str], now: float):
        """Fetch market news from Finnhub and ingest into NewsFeatureService."""
        url = "https://finnhub.io/api/v1/news"
        params = {"category": "general", "token": self._finnhub_key}
        try:
            resp = await self._client.get(url, params=params)
            resp.raise_for_status()
            articles = resp.json()

            if not isinstance(articles, list):
                logger.warning(f"Finnhub news unexpected response: {type(articles)}")
                return

            count = 0
            for article in articles[:50]:  # Cap at 50
                headline = article.get("headline", "")
                summary = article.get("summary", "")
                ts = article.get("datetime", now)
                related = article.get("related", "").upper()

                # Simple sentiment heuristic from headline keywords
                sentiment = self._headline_sentiment(headline + " " + summary)

                # Ingest for matching symbols or as general market news
                matched = False
                for sym in symbols:
                    if sym.upper() in related or sym.upper() in headline.upper():
                        self._fs.news.ingest(sym, sentiment, headline, ts=float(ts))
                        matched = True
                        count += 1

                if not matched:
                    # General market news — ingest for all active symbols with lower weight
                    for sym in symbols[:3]:  # Limit to first 3
                        self._fs.news.ingest(sym, sentiment * 0.3, headline, ts=float(ts))
                        count += 1

            self._stats["news_fetched"] += count
            logger.info(f"Finnhub: ingested {count} news data points for {len(symbols)} symbols")

        except httpx.HTTPStatusError as e:
            self._stats["errors"] += 1
            logger.warning(f"Finnhub news HTTP error: {e.response.status_code}")
        except Exception as e:
            self._stats["errors"] += 1
            logger.warning(f"Finnhub news fetch failed: {e}")

    # ── Polygon news ──────────────────────────────────────────────────

    async def _fetch_polygon_news(self, symbols: List[str], now: float):
        """Fetch news from Polygon.io as Finnhub fallback."""
        for symbol in symbols[:5]:  # Limit to 5 symbols per refresh
            ticker = self._to_polygon_ticker(symbol)
            if not ticker:
                continue

            url = f"https://api.polygon.io/v2/reference/news"
            params = {"ticker": ticker, "limit": 10, "apiKey": self._polygon_key}
            try:
                resp = await self._client.get(url, params=params)
                resp.raise_for_status()
                data = resp.json()

                for article in data.get("results", []):
                    headline = article.get("title", "")
                    ts_str = article.get("published_utc", "")
                    sentiment = self._headline_sentiment(headline)
                    # Use current time if parsing fails
                    self._fs.news.ingest(symbol, sentiment, headline, ts=now)
                    self._stats["news_fetched"] += 1

                logger.info(f"Polygon: ingested news for {symbol}")

            except Exception as e:
                self._stats["errors"] += 1
                logger.warning(f"Polygon news for {symbol} failed: {e}")

    # ── FRED macro ────────────────────────────────────────────────────

    FRED_SERIES = {
        "cpi": "CPIAUCSL",       # Consumer Price Index
        "unemployment": "UNRATE", # Unemployment rate
        "fed_funds": "FEDFUNDS",  # Fed Funds rate
        "gdp": "GDP",            # Gross Domestic Product
        "pce": "PCEPI",          # PCE Price Index
        "t10y2y": "T10Y2Y",      # 10Y-2Y spread (recession indicator)
        "vix": "VIXCLS",         # VIX index
    }

    async def _fetch_fred_macro(self, now: float):
        """Fetch macro indicators from FRED (free, no key required for basic)."""
        fred_key = os.getenv("FRED_API_KEY", "")
        if not fred_key:
            # FRED requires an API key for full access; use neutral fallback
            logger.debug("No FRED_API_KEY — macro data will use neutral fallback")
            self._ingest_neutral_macro(now)
            return

        for label, series_id in self.FRED_SERIES.items():
            url = "https://api.stlouisfed.org/fred/series/observations"
            params = {
                "series_id": series_id,
                "api_key": fred_key,
                "file_type": "json",
                "sort_order": "desc",
                "limit": 1,
            }
            try:
                resp = await self._client.get(url, params=params)
                resp.raise_for_status()
                data = resp.json()
                observations = data.get("observations", [])

                if observations:
                    obs = observations[0]
                    value = obs.get("value", ".")
                    if value != ".":
                        self._fs.macro.ingest(
                            label, float(value), f"{label.upper()}: {value}", ts=now
                        )
                        self._stats["macro_fetched"] += 1

            except Exception as e:
                self._stats["errors"] += 1
                logger.warning(f"FRED {label} fetch failed: {e}")

        logger.info(f"FRED: macro refresh complete ({self._stats['macro_fetched']} points)")

    def _ingest_neutral_macro(self, now: float):
        """Neutral macro fallback — zero surprise, not random."""
        for label in self.FRED_SERIES:
            self._fs.macro.ingest(label, 0.0, f"{label.upper()}: no data", ts=now)
        self._stats["macro_fetched"] += len(self.FRED_SERIES)

    # ── CoinGecko on-chain / crypto ───────────────────────────────────

    COINGECKO_IDS = {
        "BTC": "bitcoin",
        "ETH": "ethereum",
        "SOL": "solana",
        "BONK": "bonk",
        "WIF": "dogwifcoin",
        "AVAX": "avalanche-2",
        "MATIC": "matic-network",
        "LINK": "chainlink",
    }

    _cg_backoff_until: float = 0.0   # timestamp until which CoinGecko calls are suppressed
    _cg_consecutive_429s: int = 0    # consecutive 429 counter for exponential backoff

    async def _fetch_coingecko(self, symbols: List[str], now: float):
        """Fetch crypto market data from CoinGecko (free tier)."""
        # Respect backoff window from previous 429s
        if now < self._cg_backoff_until:
            remaining = int(self._cg_backoff_until - now)
            logger.debug(f"CoinGecko: backing off for {remaining}s more (rate-limited)")
            return

        # Map symbols to CoinGecko IDs
        ids = []
        sym_map = {}
        for sym in symbols:
            cg_id = self.COINGECKO_IDS.get(sym.upper())
            if cg_id:
                ids.append(cg_id)
                sym_map[cg_id] = sym

        if not ids:
            return

        url = "https://api.coingecko.com/api/v3/coins/markets"
        params = {
            "vs_currency": "usd",
            "ids": ",".join(ids),
            "order": "market_cap_desc",
            "per_page": 50,
            "page": 1,
            "sparkline": "false",
            "price_change_percentage": "1h,24h,7d",
        }
        try:
            resp = await self._client.get(url, params=params)
            resp.raise_for_status()
            coins = resp.json()

            # Success — reset backoff state
            self._cg_consecutive_429s = 0

            for coin in coins:
                cg_id = coin.get("id", "")
                sym = sym_map.get(cg_id, cg_id.upper())
                chain = "solana" if sym in ("SOL", "BONK", "WIF") else "ethereum"

                metrics = {
                    "price_usd": coin.get("current_price", 0) or 0,
                    "market_cap_usd": coin.get("market_cap", 0) or 0,
                    "volume_24h_usd": coin.get("total_volume", 0) or 0,
                    "price_change_1h_pct": coin.get("price_change_percentage_1h_in_currency", 0) or 0,
                    "price_change_24h_pct": coin.get("price_change_percentage_24h", 0) or 0,
                    "price_change_7d_pct": coin.get("price_change_percentage_7d_in_currency", 0) or 0,
                    "circulating_supply": coin.get("circulating_supply", 0) or 0,
                    "ath_change_pct": coin.get("ath_change_percentage", 0) or 0,
                }

                self._fs.onchain.ingest(chain, sym, metrics, ts=now)
                self._stats["onchain_fetched"] += 1

            logger.info(f"CoinGecko: ingested data for {len(coins)} coins")

        except httpx.HTTPStatusError as e:
            self._stats["errors"] += 1
            status = e.response.status_code
            if status == 429:
                self._cg_consecutive_429s += 1
                # Exponential backoff: 60s, 120s, 240s, … capped at 600s
                backoff_secs = min(60 * (2 ** (self._cg_consecutive_429s - 1)), 600)
                self._cg_backoff_until = now + backoff_secs
                logger.warning(
                    f"CoinGecko rate-limited (429). Backing off {backoff_secs}s "
                    f"(attempt {self._cg_consecutive_429s})"
                )
            else:
                logger.warning(f"CoinGecko HTTP error: {status}")
        except Exception as e:
            self._stats["errors"] += 1
            logger.warning(f"CoinGecko fetch failed: {e}")

    # ── Helpers ───────────────────────────────────────────────────────

    def _should_fetch(self, feed_name: str, now: float) -> bool:
        last = self._last_fetch.get(feed_name, 0)
        return (now - last) >= _MIN_FETCH_INTERVAL

    @staticmethod
    def _headline_sentiment(text: str) -> float:
        """Simple keyword-based sentiment scoring (-1 to 1).

        For production, replace with a proper NLP model or API.
        """
        text_lower = text.lower()

        positive = [
            "surge", "rally", "gain", "bullish", "beat", "exceed",
            "upgrade", "buy", "growth", "record", "soar", "jump",
            "breakout", "outperform", "strong", "positive", "optimistic",
            "approval", "profit", "boost", "innovation", "partnership",
        ]
        negative = [
            "crash", "drop", "fall", "bearish", "miss", "decline",
            "downgrade", "sell", "loss", "plunge", "tank", "dump",
            "breakdown", "underperform", "weak", "negative", "pessimistic",
            "reject", "deficit", "cut", "layoff", "bankruptcy", "fraud",
        ]

        pos_count = sum(1 for w in positive if w in text_lower)
        neg_count = sum(1 for w in negative if w in text_lower)
        total = pos_count + neg_count

        if total == 0:
            return 0.0  # Neutral, not random

        return max(-1.0, min(1.0, (pos_count - neg_count) / total))

    @staticmethod
    def _to_polygon_ticker(symbol: str) -> Optional[str]:
        """Map MERID symbol to Polygon ticker (equities only)."""
        crypto = {"BTC", "ETH", "SOL", "BONK", "WIF", "AVAX", "MATIC", "LINK"}
        if symbol.upper() in crypto:
            return f"X:{symbol.upper()}USD"
        return symbol.upper()


# ── Singleton ─────────────────────────────────────────────────────────

_live_feed_mgr: Optional[LiveFeedManager] = None


def get_live_feed_manager() -> LiveFeedManager:
    global _live_feed_mgr
    if _live_feed_mgr is None:
        _live_feed_mgr = LiveFeedManager()
    return _live_feed_mgr
