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
import threading
import time
from typing import Any, Dict, List, Optional

import httpx

from utils.logger import get_logger

logger = get_logger("merid.signals.live_feeds")


def _build_coingecko_ids() -> dict:
    """Build base→coingecko_id map from the top-50 asset universe."""
    try:
        from data.asset_universe import ASSET_UNIVERSE
        return {
            k: v.coingecko_id
            for k, v in ASSET_UNIVERSE.items()
            if "-PERP" not in k and k != "BNBUS" and v.coingecko_id
        }
    except Exception:
        return {
            "BTC": "bitcoin", "ETH": "ethereum", "SOL": "solana",
            "BONK": "bonk", "WIF": "dogwifcoin", "AVAX": "avalanche-2",
            "POL": "matic-network", "LINK": "chainlink",
        }


# Timeouts and rate limiting
_HTTP_TIMEOUT = 3.0  # External feeds are non-critical enrichment; keep tight to avoid blocking executor
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
        """Refresh all feeds for the given symbols (concurrently).
        
        P1-HARDENING: Per-feed timeouts (1.0s) prevent single slow feed from blocking.
        """
        import asyncio
        now = now or time.time()
        
        # P1-HARDENING: Per-feed timeouts to stay within features budget
        async def _timed_refresh_news():
            try:
                await asyncio.wait_for(self.refresh_news(symbols, now), timeout=1.0)
            except asyncio.TimeoutError:
                logger.warning("[BUDGET] News feed refresh timed out after 1.0s")
                self._stats["errors"] += 1
        
        async def _timed_refresh_macro():
            try:
                await asyncio.wait_for(self.refresh_macro(now), timeout=1.0)
            except asyncio.TimeoutError:
                logger.warning("[BUDGET] Macro feed refresh timed out after 1.0s")
                self._stats["errors"] += 1
        
        async def _timed_refresh_onchain():
            try:
                await asyncio.wait_for(self.refresh_onchain(symbols, now), timeout=1.0)
            except asyncio.TimeoutError:
                logger.warning("[BUDGET] On-chain feed refresh timed out after 1.0s")
                self._stats["errors"] += 1
        
        await asyncio.gather(
            _timed_refresh_news(),
            _timed_refresh_macro(),
            _timed_refresh_onchain(),
            return_exceptions=True,
        )

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

    def get_feed_health(self) -> Dict[str, Any]:
        """Return health metrics for news/social feeds for guard/alerting.
        
        Returns:
            Dict with health status for each feed type:
            - news: finnhub health (configured, last fetch, error state, zero-data count)
            - macro: fred health
            - onchain: coingecko health
        """
        now = time.time()
        
        # News feed health (Finnhub)
        news_last_fetch = self._last_fetch.get("news", 0)
        news_api_count = self._last_fetch.get("news_api_count", 0)
        news_ingested = self._last_fetch.get("news_ingested_count", 0)
        news_error = self._last_fetch.get("news_error")
        news_error_ts = self._last_fetch.get("news_error_ts", 0)
        
        # Determine news health status
        NEWS_STALE_THRESHOLD = 300  # 5 minutes
        news_age = now - news_last_fetch if news_last_fetch else float('inf')
        
        if not self._finnhub_key:
            news_status = "not_configured"
        elif news_error and (now - news_error_ts) < 300:  # Error within last 5 min
            news_status = "error"
        elif news_age > NEWS_STALE_THRESHOLD:
            news_status = "stale"
        elif news_api_count == 0 and news_last_fetch > 0:
            # API returned 0 articles on last fetch
            news_status = "zero_data"
        elif news_ingested == 0 and news_api_count > 0:
            # API returned articles but none matched symbols
            news_status = "no_matches"
        else:
            news_status = "healthy"
        
        # Macro health (FRED)
        macro_last_fetch = self._last_fetch.get("macro", 0)
        macro_age = now - macro_last_fetch if macro_last_fetch else float('inf')
        macro_status = "healthy" if macro_age < NEWS_STALE_THRESHOLD else "stale"
        
        # Onchain health (CoinGecko)
        onchain_last_fetch = self._last_fetch.get("onchain", 0)
        onchain_age = now - onchain_last_fetch if onchain_last_fetch else float('inf')
        onchain_status = "healthy" if onchain_age < NEWS_STALE_THRESHOLD else "stale"
        
        return {
            "news": {
                "status": news_status,
                "configured": bool(self._finnhub_key),
                "last_fetch_age_s": round(news_age, 1) if news_age < 86400 else None,
                "api_articles_last_fetch": news_api_count,
                "ingested_last_fetch": news_ingested,
                "error": news_error if news_error and (now - news_error_ts) < 300 else None,
            },
            "macro": {
                "status": macro_status,
                "last_fetch_age_s": round(macro_age, 1) if macro_age < 86400 else None,
            },
            "onchain": {
                "status": onchain_status,
                "last_fetch_age_s": round(onchain_age, 1) if onchain_age < 86400 else None,
            },
            "overall": "healthy" if all(s["status"] in ("healthy", "not_configured") 
                                         for s in [news_status, macro_status, onchain_status]) else "degraded",
            "timestamp": now,
        }

    async def close(self):
        await self._client.aclose()

    # ── Finnhub news ──────────────────────────────────────────────────

    async def _fetch_finnhub_news(self, symbols: List[str], now: float):
        """Fetch market news from Finnhub and ingest into NewsFeatureService."""
        url = "https://finnhub.io/api/v1/news"
        params = {"category": "general", "token": self._finnhub_key}
        
        # Track API-level metrics for health monitoring
        api_articles_received = 0
        api_error = None
        
        try:
            resp = await self._client.get(url, params=params)
            resp.raise_for_status()
            articles = resp.json()

            if not isinstance(articles, list):
                logger.warning(f"Finnhub news unexpected response: {type(articles)}")
                self._stats["errors"] += 1
                return

            api_articles_received = len(articles)
            
            count = 0
            matched_symbols = set()
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
                        matched_symbols.add(sym)

                if not matched:
                    # General market news — ingest for all active symbols with lower weight
                    for sym in symbols[:3]:  # Limit to first 3
                        self._fs.news.ingest(sym, sentiment * 0.3, headline, ts=float(ts))
                        count += 1

            self._stats["news_fetched"] += count
            
            # Enhanced logging to distinguish API response vs filtering results
            if api_articles_received == 0:
                logger.warning(f"Finnhub: API returned 0 articles (check API key/category)")
            elif count == 0:
                logger.warning(
                    f"Finnhub: API returned {api_articles_received} articles but 0 matched "
                    f"symbols {symbols[:5]}{'...' if len(symbols) > 5 else ''}"
                )
            else:
                logger.info(
                    f"Finnhub: API={api_articles_received} articles, ingested={count} "
                    f"for {len(matched_symbols)}/{len(symbols)} symbols"
                )
                
            # Store health metrics for guard/alerting
            self._last_fetch["news"] = now
            self._last_fetch["news_api_count"] = api_articles_received
            self._last_fetch["news_ingested_count"] = count
            self._last_fetch["news_matched_symbols"] = len(matched_symbols)

        except httpx.HTTPStatusError as e:
            self._stats["errors"] += 1
            api_error = f"HTTP {e.response.status_code}"
            logger.warning(f"Finnhub news HTTP error: {e.response.status_code}")
            # Store error for health monitoring
            self._last_fetch["news_error"] = api_error
            self._last_fetch["news_error_ts"] = now
        except Exception as e:
            self._stats["errors"] += 1
            api_error = f"{type(e).__name__}: {e}"
            logger.debug(f"Finnhub news fetch failed: {type(e).__name__}: {e}")
            # Store error for health monitoring
            self._last_fetch["news_error"] = api_error
            self._last_fetch["news_error_ts"] = now

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
        """Fetch macro indicators from FRED (free, no key required for basic).

        All series are fetched **concurrently** to avoid the sequential
        7×timeout worst-case that was causing 'features' step timeouts.
        """
        import asyncio

        fred_key = os.getenv("FRED_API_KEY", "")
        if not fred_key:
            # FRED requires an API key for full access; use neutral fallback
            logger.debug("No FRED_API_KEY — macro data will use neutral fallback")
            self._ingest_neutral_macro(now)
            return

        async def _fetch_one(label: str, series_id: str):
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
                logger.debug(f"FRED {label} fetch failed: {type(e).__name__}: {e}")

        await asyncio.gather(
            *[_fetch_one(label, sid) for label, sid in self.FRED_SERIES.items()],
            return_exceptions=True,
        )

        logger.info(f"FRED: macro refresh complete ({self._stats['macro_fetched']} points)")

    def _ingest_neutral_macro(self, now: float):
        """Neutral macro fallback — zero surprise, not random."""
        for label in self.FRED_SERIES:
            self._fs.macro.ingest(label, 0.0, f"{label.upper()}: no data", ts=now)
        self._stats["macro_fetched"] += len(self.FRED_SERIES)

    # ── CoinGecko on-chain / crypto ───────────────────────────────────

    COINGECKO_IDS: Dict[str, str] = _build_coingecko_ids()

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
            logger.warning(f"CoinGecko fetch failed: {type(e).__name__}: {e}")

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
        crypto = {"BTC", "ETH", "SOL", "BONK", "WIF", "AVAX", "POL", "LINK"}
        if symbol.upper() in crypto:
            return f"X:{symbol.upper()}USD"
        return symbol.upper()


# ── Singleton ─────────────────────────────────────────────────────────

_live_feed_mgr: Optional[LiveFeedManager] = None
_live_feed_mgr_lock = threading.Lock()


def get_live_feed_manager() -> LiveFeedManager:
    global _live_feed_mgr
    if _live_feed_mgr is None:
        with _live_feed_mgr_lock:
            if _live_feed_mgr is None:
                _live_feed_mgr = LiveFeedManager()
    return _live_feed_mgr
