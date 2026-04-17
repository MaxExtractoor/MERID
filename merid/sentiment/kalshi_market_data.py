"""
Kalshi Market Data Integration - Public API Integration for Sentiment Agent

Uses Kalshi's public market data endpoints to drive sentiment analysis with
real-time market tickers, event data, and volume filtering.
"""

from __future__ import annotations

import os
import requests
import time
from typing import Dict, List, Optional, Any
from dataclasses import dataclass

from config.kalshi_crypto_config import ACTIVE_CRYPTO_ASSETS
from merid.sentiment.news_config import CRYPTO_ASSETS, NEWS_TOPICS
from utils.logger import get_logger

logger = get_logger("merid.sentiment.kalshi_market_data")

# Kalshi public API endpoints - read from env to support demo/live modes
BASE_URL = os.getenv("KALSHI_API_BASE_URL", "https://demo-api.kalshi.co/trade-api/v2")


@dataclass
class KalshiMarket:
    """Kalshi market data structure."""
    ticker: str               # market_ticker e.g. "KXBTC15M-25MAR26"
    event_ticker: str         # event_ticker e.g. "CRYPTO_BTC_2026"
    title: str                # e.g. "BTC Up or Down - 15 minutes"
    category: str             # e.g. "crypto"
    volume: float             # USD volume
    status: str               # e.g. "open"
    close_time: Optional[str] # ISO timestamp
    series_ticker: Optional[str] = None  # e.g. "KXBTC15M"
    yes_price: Optional[float] = None     # Current YES price
    day_change: Optional[float] = None    # Daily change percentage
    last_price: Optional[float] = None    # Last price (fallback)


@dataclass
class KalshiEvent:
    """Kalshi event data structure."""
    event_ticker: str
    title: str
    category: str
    status: str
    markets: List[KalshiMarket]


class KalshiMarketDataClient:
    """Client for fetching Kalshi market data via public API."""
    
    def __init__(self, base_url: str = BASE_URL):
        self.base_url = base_url
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "MERID-Sentiment-Agent/1.0"
        })
    
    def get_all_crypto_markets(self, status: str = "open") -> List[Dict[str, Any]]:
        """Fetch all crypto markets (any frequency) with cursor pagination."""
        markets = []
        cursor = None

        while True:
            params = {"status": status, "limit": 500}
            if cursor:
                params["cursor"] = cursor
            resp = self.session.get(f"{self.base_url}/markets", params=params, timeout=5)
            resp.raise_for_status()
            data = resp.json()
            for m in data["markets"]:
                if m.get("category") == "crypto":
                    markets.append(m)
            cursor = data.get("cursor")
            if not cursor:
                break

        return markets
    
    def get_all_crypto_markets_full(self, status: str = "open") -> List[Dict[str, Any]]:
        """Fetch all crypto markets with larger page size for full list."""
        all_markets = []
        cursor = None
        while True:
            params = {"status": status, "limit": 1000}
            if cursor:
                params["cursor"] = cursor
            resp = self.session.get(f"{self.base_url}/markets", params=params, timeout=5)
            resp.raise_for_status()
            data = resp.json()

            for m in data["markets"]:
                if m.get("category") == "crypto":
                    all_markets.append(m)

            cursor = data.get("cursor")
            if not cursor:
                break
        return all_markets
    
    def fetch_crypto_markets(self, status: str = "open") -> List[KalshiMarket]:
        """Fetch all crypto markets and convert to KalshiMarket objects."""
        markets_data = self.get_all_crypto_markets(status)
        return [
            KalshiMarket(
                ticker=m["ticker"],
                event_ticker=m["event_ticker"],
                title=m["title"],
                category=m["category"],
                volume=m.get("volume", 0.0),
                status=m.get("status", "unknown"),
                close_time=m.get("close_time"),
                series_ticker=m.get("series_ticker"),
                yes_price=m.get("yes_price"),
                day_change=m.get("day_change"),
                last_price=m.get("last_price")
            )
            for m in markets_data
        ]
    
    def fetch_15m_crypto_markets(self, status: str = "open") -> List[KalshiMarket]:
        """Fetch 15-minute crypto markets specifically."""
        all_crypto = self.fetch_crypto_markets(status)
        return [
            m for m in all_crypto
            if "15 minutes" in m.title
        ]
    
    def get_orderbook(self, ticker: str) -> Dict[str, Any]:
        """Get orderbook for a specific market."""
        resp = self.session.get(f"{self.base_url}/markets/{ticker}/orderbook", timeout=5)
        resp.raise_for_status()
        return resp.json()["orderbook"]
    
    def fetch_event(self, event_ticker: str) -> Optional[KalshiEvent]:
        """Fetch full event data by ticker."""
        try:
            resp = self.session.get(
                f"{self.base_url}/events/{event_ticker}",
                timeout=10
            )
            resp.raise_for_status()
            data = resp.json()
            event_data = data.get("event") or data
            
            return KalshiEvent(
                event_ticker=event_data["event_ticker"],
                title=event_data["title"],
                category=event_data["category"],
                status=event_data["status"],
                markets=[]  # Would need additional call to get markets
            )
            
        except Exception as exc:
            logger.warning("Failed to fetch event %s: %s", event_ticker, exc)
            return None
    
    def filter_high_volume_markets(
        self, 
        markets: List[KalshiMarket], 
        min_volume_usd: float = 5000
    ) -> List[KalshiMarket]:
        """Filter markets by minimum USD volume."""
        filtered = [m for m in markets if m.get("volume", 0) >= min_volume_usd]
        logger.info(
            "Filtered to %d high-volume markets (min_volume=$%.0f)", 
            len(filtered), min_volume_usd
        )
        return filtered


class KalshiSentimentQueryBuilder:
    """Builds sentiment queries from Kalshi market data."""
    
    @staticmethod
    def topic_for_kalshi_event(event: KalshiEvent) -> str:
        """Map Kalshi event category to NEWS_TOPICS key."""
        cat = event.category.lower()
        
        # Direct mapping
        if cat in NEWS_TOPICS:
            return cat
        
        # Fallbacks: e.g. "crypto/frequency/fifteen_min" → "crypto"
        if "crypto" in cat:
            return "crypto"
        if "stocks" in cat or "equities" in cat:
            return "equities"
        if "economics" in cat:
            return "economics"
        if "politics" in cat:
            return "politics"
        
        return "mentions"
    
    @staticmethod
    def topic_for_series(series_ticker: str, category: str) -> str:
        """Map series_ticker and category to NEWS_TOPICS key."""
        st = series_ticker.lower()
        cat = category.lower()

        # direct match in NEWS_TOPICS
        if st in NEWS_TOPICS:
            return st
        # broad category mapping
        if "crypto" in cat:
            return "crypto"
        if "stocks" in cat:
            return "equities"
        # example series-specific overrides
        if "kxbtc15m" in st:
            return "crypto_btc_intraday"
        if "kxeth15m" in st:
            return "crypto_eth_intraday"
        return "mentions"
    
    @staticmethod
    def infer_asset_from_title(title: str) -> Optional[str]:
        """Infer crypto asset from market title."""
        title_upper = title.upper()
        for asset in CRYPTO_ASSETS:
            if asset in title_upper:
                return asset
        return None
    
    @staticmethod
    def build_queries_for_market(market: KalshiMarket) -> Dict[str, Any]:
        """Build sentiment queries for a specific Kalshi market."""
        title = market.title
        event = KalshiSentimentQueryBuilder._get_event_cached(market.event_ticker)
        
        # Use series_ticker for more precise topic mapping
        if market.series_ticker:
            topic_key = KalshiSentimentQueryBuilder.topic_for_series(
                market.series_ticker, market.category
            )
        else:
            topic_key = KalshiSentimentQueryBuilder.topic_for_kalshi_event(event)
        
        topic_cfg = NEWS_TOPICS.get(topic_key)
        
        # Infer asset from title
        asset = KalshiSentimentQueryBuilder.infer_asset_from_title(title)
        
        # Base keywords and hashtags
        keywords = [title]
        hashtags = []
        subreddits = []
        
        if topic_cfg:
            keywords = list(topic_cfg.keywords[:8]) + [title]
            hashtags = list(topic_cfg.hashtags[:6])
            subreddits = list(topic_cfg.subreddits[:4])
        
        # Asset-specific augmentation
        if asset and asset in CRYPTO_ASSETS:
            acfg = CRYPTO_ASSETS[asset]
            hashtags = list(dict.fromkeys(list(acfg.hashtags[:4]) + hashtags))[:6]
            keywords = list(acfg.names) + keywords
            subreddits = list(dict.fromkeys(list(acfg.subreddits[:2]) + subreddits))[:4]
        
        # For crypto category, add focused 15m crypto queries (all canonical assets)
        if market.category == "crypto" and asset in ACTIVE_CRYPTO_ASSETS:
            crypto_keywords = [
                f"{asset} price",
                f"{asset} 15m",
                f"{asset} 15 min",
                f"{asset} Kalshi",
                f"{asset} prediction",
                f"{asset} up or down",
            ]
            keywords = crypto_keywords + keywords

            tag_extra = {
                "BTC": ("#bitcoin", "#btc"),
                "ETH": ("#ethereum", "#eth"),
                "SOL": ("#solana", "#sol"),
                "XRP": ("#xrp", "#ripple"),
                "DOGE": ("#dogecoin", "#doge"),
            }.get(asset, (f"#{asset.lower()}",))
            crypto_hashtags = [f"#{asset.lower()}", *tag_extra]
            hashtags = crypto_hashtags + hashtags
            hashtags = list(dict.fromkeys(hashtags))[:6]
        
        return {
            "topic_key": topic_key,
            "asset": asset,
            "keywords": keywords[:10],
            "hashtags": hashtags[:6],
            "subreddits": subreddits[:4],
            "market_ticker": market.ticker,
            "event_ticker": market.event_ticker,
            "series_ticker": market.series_ticker,
        }
    
    @staticmethod
    def _get_event_cached(event_ticker: str) -> Optional[KalshiEvent]:
        """Get event data with simple caching."""
        # Simple in-memory cache (could be replaced with LocalDataCache)
        if not hasattr(KalshiSentimentQueryBuilder, "_event_cache"):
            KalshiSentimentQueryBuilder._event_cache = {}
            KalshiSentimentQueryBuilder._cache_timestamps = {}
        
        cache = KalshiSentimentQueryBuilder._event_cache
        timestamps = KalshiSentimentQueryBuilder._cache_timestamps
        
        now = time.time()
        # Cache for 5 minutes
        if (event_ticker in cache and 
            event_ticker in timestamps and 
            now - timestamps[event_ticker] < 300):
            return cache[event_ticker]
        
        # Fetch fresh data
        client = KalshiMarketDataClient()
        event = client.fetch_event(event_ticker)
        
        if event:
            cache[event_ticker] = event
            timestamps[event_ticker] = now
        
        return event


class KalshiSentimentConfigBuilder:
    """Builds sentiment configuration from Kalshi market data."""
    
    def __init__(self, client: Optional[KalshiMarketDataClient] = None):
        self.client = client or KalshiMarketDataClient()
    
    def build_kalshi_sentiment_config(
        self, 
        min_volume_usd: float = 2000,
        max_markets: int = 50
    ) -> Dict[str, Dict[str, Any]]:
        """Build sentiment config keyed by market_ticker."""
        logger.info("Building Kalshi sentiment config...")
        
        # Fetch 15m crypto markets
        markets = self.client.fetch_15m_crypto_markets()
        logger.info("Fetched %d 15m crypto markets", len(markets))
        
        # Filter by volume
        high_volume = self.client.filter_high_volume_markets(markets, min_volume_usd)
        logger.info("Filtered to %d high-volume markets", len(high_volume))
        
        # Limit to prevent excessive API calls
        if len(high_volume) > max_markets:
            high_volume = high_volume[:max_markets]
            logger.info("Limited to %d markets for API rate limits", max_markets)
        
        # Build queries for each market
        config = {}
        for market in high_volume:
            queries = KalshiSentimentQueryBuilder.build_queries_for_market(market)
            if queries:
                config[market.ticker] = queries
                logger.debug(
                    "Built queries for %s (%s): %d keywords, %d hashtags",
                    market.ticker, market.asset or "unknown", 
                    len(queries["keywords"]), len(queries["hashtags"])
                )
        
        logger.info("Built sentiment config for %d Kalshi markets", len(config))
        return config
    
    def refresh_config(self, existing_config: Dict[str, Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
        """Refresh existing config with new market data."""
        new_config = self.build_kalshi_sentiment_config()
        
        # Merge with existing config, preserving customizations
        merged = {**new_config}
        for ticker, queries in existing_config.items():
            if ticker not in merged:
                merged[ticker] = queries  # Keep old config for delisted markets
        
        return merged


# Singleton instance
_kalshi_client: Optional[KalshiMarketDataClient] = None

def get_kalshi_market_client() -> KalshiMarketDataClient:
    """Get singleton Kalshi market data client."""
    global _kalshi_client
    if _kalshi_client is None:
        _kalshi_client = KalshiMarketDataClient()
    return _kalshi_client


def yes_sentiment_from_markets(markets: List[KalshiMarket]) -> List[Dict[str, Any]]:
    """
    Build simple sentiment signals from yes_price change for 15m crypto.
    Assumes each market dict has yes_price and maybe day_change or last_price_hist.
    """
    signals = []
    for m in markets:
        title = m.title
        if "15 minutes" not in title:
            continue

        yes_price = m.yes_price or m.last_price
        pct_change = m.day_change  # or compute from history if you have it

        if yes_price is None or pct_change is None:
            continue

        direction = "bullish" if pct_change > 0 else "bearish" if pct_change < 0 else "neutral"
        strength = min(1.0, abs(pct_change) / 0.15)  # scale 0–1 by 15% move

        signals.append({
            "ticker": m.ticker,
            "series_ticker": m.series_ticker,
            "title": title,
            "direction": direction,
            "strength": round(strength, 3),
            "yes_price": yes_price,
            "pct_change": pct_change,
        })
    return signals


def build_agent_view(market: KalshiMarket, client: Optional[KalshiMarketDataClient] = None) -> Dict[str, Any]:
    """Combine event data + orderbook for agent decisions."""
    if client is None:
        client = get_kalshi_market_client()
    
    try:
        ob = client.get_orderbook(market.ticker)
    except Exception as exc:
        logger.warning("Failed to get orderbook for %s: %s", market.ticker, exc)
        return {
            "ticker": market.ticker,
            "series_ticker": market.series_ticker,
            "title": market.title,
            "category": market.category,
            "volume": market.volume,
            "error": "orderbook_unavailable"
        }
    
    yes_side = ob.get("yes", [])
    no_side = ob.get("no", [])

    yes_bid_c, yes_bid_qty = (yes_side[-1] if yes_side else (None, 0))
    no_bid_c, no_bid_qty = (no_side[-1] if no_side else (None, 0))

    if yes_bid_c is not None and no_bid_c is not None:
        yes_bid = yes_bid_c / 100.0
        yes_ask = (100 - no_bid_c) / 100.0
        spread_c = (yes_ask - yes_bid) * 100
    else:
        yes_bid = yes_ask = spread_c = None

    return {
        "ticker": market.ticker,
        "series_ticker": market.series_ticker,
        "title": market.title,
        "category": market.category,
        "volume": market.volume,
        "yes_bid_c": yes_bid_c,
        "yes_ask_c": 100 - no_bid_c if no_bid_c is not None else None,
        "yes_bid": yes_bid,
        "yes_ask": yes_ask,
        "spread_cents": spread_c,
        "yes_depth": yes_bid_qty,
        "no_depth": no_bid_qty,
        "yes_price": market.yes_price,
        "day_change": market.day_change,
    }


# ── Kalshi-Specific Implementations ─────────────────────────────────────

from collections import deque

class YesMomentum:
    """Calculate 15m yes_price momentum signals using price history."""
    
    def __init__(self, window: int = 4):
        self.window = window
        self.history: Dict[str, deque[int]] = {}

    def update(self, ticker: str, yes_price_c: int) -> float:
        """Update momentum for a ticker based on new yes price."""
        dq = self.history.setdefault(ticker, deque(maxlen=self.window))
        dq.append(yes_price_c)
        if len(dq) < 2:
            return 0.0
        # simple momentum: latest minus oldest, normalized to dollars
        return (dq[-1] - dq[0]) / 100.0

def compute_15m_momentum(markets: List[Dict[str, Any]], mom: YesMomentum) -> List[Dict[str, Any]]:
    """Compute momentum signals for 15m crypto markets."""
    signals = []
    for m in markets:
        if "15 minutes" not in m.get("title", ""):
            continue
        yp = m.get("yes_price") or m.get("last_price")
        if yp is None:
            continue
        mom_val = mom.update(m["ticker"], int(yp))
        signals.append({
            "ticker": m["ticker"],
            "title": m["title"],
            "yes_price_c": int(yp),
            "momentum": mom_val,         # + = up, - = down
        })
    return signals


def get_event(event_ticker: str) -> Dict[str, Any]:
    """Get Kalshi event data by ticker."""
    resp = requests.get(f"{BASE_URL}/events/{event_ticker}", timeout=5)
    resp.raise_for_status()
    return resp.json()["event"]


def headline_for_event(event_ticker: str) -> str:
    """Get headline/title for a Kalshi event."""
    ev = get_event(event_ticker)
    # e.g. "BTC Up or Down - 15 minutes"
    return ev.get("title") or ev.get("name") or event_ticker


def backtest_sentiment(
    price_series: List[Dict[str, Any]],   # [{ts, yes_price_c}]
    sentiment_series: List[Dict[str, Any]],  # [{ts, score}]
    horizon_secs: int = 900,
) -> List[Dict[str, Any]]:
    """
    Simple backtest: if sentiment_score > 0 at time t → buy YES,
    hold to t+horizon and measure P&L in cents.
    """
    results = []
    # assume both lists are sorted by ts
    for s in sentiment_series:
        ts = s["ts"]
        score = s["score"]
        direction = 1 if score > 0 else -1 if score < 0 else 0
        if direction == 0:
            continue

        # find price at entry
        entry = next((p for p in price_series if p["ts"] >= ts), None)
        exit_ = next((p for p in price_series if p["ts"] >= ts + horizon_secs), None)
        if not entry or not exit_:
            continue

        entry_c = entry["yes_price_c"]
        exit_c = exit_["yes_price_c"]

        # mark‑to‑market P&L (before fees, not settlement)
        pnl_c = direction * (exit_c - entry_c)

        results.append({
            "ts": ts,
            "score": score,
            "dir": direction,
            "entry_c": entry_c,
            "exit_c": exit_c,
            "pnl_c": pnl_c,
        })
    return results


def enrich_crypto_markets_with_news(markets: List[Dict[str, Any]], news_client) -> List[Dict[str, Any]]:
    """
    Integrate Kalshi markets with news API sentiment.
    
    news_client.get_sentiment(headline: str) -> {score, volume}
    """
    enriched = []
    for m in markets:
        if m.get("category") != "crypto":
            continue
        ev_ticker = m["event_ticker"]
        headline = headline_for_event(ev_ticker)
        news = news_client.get_sentiment(headline)
        enriched.append({
            "ticker": m["ticker"],
            "event_ticker": ev_ticker,
            "title": m["title"],
            "yes_price": m.get("yes_price") or m.get("last_price"),
            "volume": m.get("volume"),
            "news_headline": headline,
            "news_score": news.get("score", 0.0),
            "news_volume": news.get("volume", 0),
        })
    return enriched


# ── Real-Time WebSocket Streaming ─────────────────────────────────────

import asyncio
import json
import os
import websockets
from datetime import datetime, timezone

WS_URL = "wss://api.elections.kalshi.com/trade-api/ws/v2"  # check env (demo vs prod)

class KalshiWebSocketStreamer:
    """Real-time Kalshi WebSocket streaming for yes_price data."""
    
    def __init__(self, api_key: str, api_signature: str, api_timestamp: str):
        self.api_key = api_key
        self.api_signature = api_signature
        self.api_timestamp = api_timestamp
        self.headers = {
            "KALSHI-ACCESS-KEY": api_key,
            "KALSHI-ACCESS-SIGNATURE": api_signature,
            "KALSHI-ACCESS-TIMESTAMP": api_timestamp,
        }
    
    async def yes_price_stream(self, tickers: List[str], callback=None):
        """Stream yes_price ticks for specified tickers."""
        async with websockets.connect(WS_URL, additional_headers=self.headers) as ws:
            # subscribe to trades for yes_price ticks
            sub_msg = {
                "type": "subscribe",
                "channels": [
                    {"name": "trades", "symbols": tickers},
                ],
            }
            await ws.send(json.dumps(sub_msg))

            async for raw in ws:
                msg = json.loads(raw)
                if msg.get("type") == "trade":
                    t = msg["trade"]
                    ticker = t["ticker"]
                    yes_c = t["yes_price"]          # in cents
                    ts = datetime.fromisoformat(t["created_time"].replace("Z", "+00:00"))
                    
                    trade_data = {
                        "ts": ts,
                        "ticker": ticker,
                        "yes_price_c": yes_c,
                        "yes_price": yes_c / 100.0,
                        "side": t.get("side"),
                        "size": t.get("size"),
                    }
                    
                    if callback:
                        await callback(trade_data)
                    else:
                        print(f"{ts.isoformat()} {ticker} yes={yes_c/100:.2f}")


# ── Historical Data Fetching ───────────────────────────────────────────

def get_yes_price_history(ticker: str, start_iso: str, end_iso: str) -> List[Dict[str, Any]]:
    """Return [{ts, yes_price_c}] for a ticker over a window."""
    out = []
    cursor = None
    params = {
        "ticker": ticker,
        "start_time": start_iso,
        "end_time": end_iso,
        "limit": 500,
    }
    while True:
        p = dict(params)
        if cursor:
            p["cursor"] = cursor
        r = requests.get(f"{BASE_URL}/trades", params=p, timeout=5)
        r.raise_for_status()
        data = r.json()
        for tr in data["trades"]:
            out.append({
                "ts": tr["created_time"],
                "yes_price_c": tr["yes_price"],
                "size": tr.get("size"),
                "side": tr.get("side"),
            })
        cursor = data.get("cursor")
        if not cursor:
            break
    return out


# ── Advanced Backtesting ───────────────────────────────────────────────

from datetime import datetime, timedelta

def parse_ts(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))

def backtest_15m_momentum(series: List[Dict[str, Any]], threshold_c: int = 3) -> List[Dict[str, Any]]:
    """
    series: sorted [{ts, yes_price_c}]
    Enter long YES if last 2 ticks up by > threshold_c, short if down.
    Exit 15m later at market yes_price.
    """
    series = sorted(series, key=lambda x: x["ts"])
    results = []
    for i in range(2, len(series)):
        t0 = parse_ts(series[i]["ts"])
        p0 = series[i]["yes_price_c"]
        p_prev = series[i-1]["yes_price_c"]
        p_prev2 = series[i-2]["yes_price_c"]

        up = p0 - p_prev > threshold_c and p_prev - p_prev2 > 0
        down = p_prev - p0 > threshold_c and p_prev2 - p_prev > 0
        if not (up or down):
            continue

        direction = 1 if up else -1
        # find exit 15m later
        exit_time = t0 + timedelta(minutes=15)
        exit_tick = next((x for x in series if parse_ts(x["ts"]) >= exit_time), None)
        if not exit_tick:
            continue
        p1 = exit_tick["yes_price_c"]
        pnl_c = direction * (p1 - p0)

        results.append({
            "entry_ts": t0.isoformat(),
            "exit_ts": exit_time.isoformat(),
            "dir": direction,
            "entry_c": p0,
            "exit_c": p1,
            "pnl_c": pnl_c,
        })
    return results


# ── Optimized Market Filtering ─────────────────────────────────────────

def get_high_volume_crypto_markets(
    status: str = "open",
    min_volume: float = 10_000.0,
) -> List[Dict[str, Any]]:
    """Fetch only high-volume crypto markets with server-side filtering."""
    markets = []
    cursor = None
    while True:
        params = {"status": status, "limit": 1000}
        if cursor:
            params["cursor"] = cursor
        r = requests.get(f"{BASE_URL}/markets", params=params, timeout=5)
        r.raise_for_status()
        data = r.json()
        for m in data["markets"]:
            if m.get("category") == "crypto" and (m.get("volume") or 0) >= min_volume:
                markets.append(m)
        cursor = data.get("cursor")
        if not cursor:
            break
    return markets


# ── Enhanced News Integration ───────────────────────────────────────────

def integrate_news_with_markets(markets: List[Dict[str, Any]], news_client) -> List[Dict[str, Any]]:
    """Integrate news sentiment scores with market data using event_ticker."""
    enriched = []
    for m in markets:
        if m.get("category") != "crypto":
            continue
        ev_ticker = m["event_ticker"]
        # minimal event fetch for better headline, or use m["title"]
        headline = m.get("title")
        news = news_client.get_sentiment(headline)
        enriched.append({
            "ticker": m["ticker"],
            "event_ticker": ev_ticker,
            "title": headline,
            "yes_price_c": m.get("yes_price") or m.get("last_price"),
            "volume": m.get("volume"),
            "news_score": news["score"],
            "news_volume": news["volume"],
        })
    return enriched


# ── Complete Production Pipeline ───────────────────────────────────────

async def production_pipeline_example():
    """
    Complete production example combining all components:
    1. Real-time WebSocket streaming
    2. Historical data backtesting
    3. High-volume market filtering
    4. News sentiment integration
    """
    
    # 1. Get high-volume crypto markets
    high_volume_markets = get_high_volume_crypto_markets(min_volume=10_000.0)
    tickers = [m["ticker"] for m in high_volume_markets if "15 minutes" in m.get("title", "")]
    print(f"Found {len(tickers)} high-volume 15m markets")
    
    # 2. Get historical data for backtesting
    end_time = datetime.now(timezone.utc)
    start_time = end_time - timedelta(days=7)
    
    all_history = []
    for ticker in tickers[:5]:  # Backtest first 5 markets
        history = get_yes_price_history(
            ticker, 
            start_time.isoformat(), 
            end_time.isoformat()
        )
        all_history.extend(history)
        print(f"Fetched {len(history)} trades for {ticker}")
    
    # 3. Run momentum backtest
    backtest_results = backtest_15m_momentum(all_history, threshold_c=3)
    total_pnl = sum(r["pnl_c"] for r in backtest_results)
    print(f"Backtest: {len(backtest_results)} trades, total PnL: {total_pnl}¢")
    
    # 4. Real-time streaming setup
    async def trade_callback(trade_data):
        """Handle incoming trade data."""
        ticker = trade_data["ticker"]
        yes_price = trade_data["yes_price"]
        print(f"Real-time {ticker}: {yes_price:.2f}")
        # Here you would:
        # - Update momentum calculations
        # - Check trading signals
        # - Execute trades if conditions met
    
    # 5. Start WebSocket streaming
    streamer = KalshiWebSocketStreamer(
        api_key=os.getenv("KALSHI_API_KEY"),
        api_signature=os.getenv("KALSHI_API_SIGNATURE"),
        api_timestamp=os.getenv("KALSHI_API_TS")
    )
    
    print("Starting real-time stream...")
    await streamer.yes_price_stream(tickers[:3], trade_callback)


# ── Streamlined Real-Time Integration ───────────────────────────────────

async def stream_yes_prices(handler, tickers: List[str] = None):
    """Stream yes_price data for 15m markets with handler callback."""
    if tickers is None:
        tickers = ["KXBTC15M", "KXETH15M"]  # default 15m series
    
    headers = {
        "KALSHI-ACCESS-KEY": os.getenv("KALSHI_API_KEY"),
        "KALSHI-ACCESS-SIGNATURE": os.getenv("KALSHI_API_SIGNATURE"),
        "KALSHI-ACCESS-TIMESTAMP": os.getenv("KALSHI_API_TS"),
    }
    
    async with websockets.connect(WS_URL, additional_headers=headers) as ws:
        sub = {
            "type": "subscribe",
            "channels": [{"name": "trades", "symbols": tickers}],
        }
        await ws.send(json.dumps(sub))
        async for raw in ws:
            msg = json.loads(raw)
            if msg.get("type") != "trade":
                continue
            tr = msg["trade"]
            ts = datetime.fromisoformat(tr["created_time"].replace("Z", "+00:00"))
            yes_c = tr["yes_price"]
            await handler({
                "ticker": tr["ticker"],
                "ts": ts,
                "yes_price_c": yes_c,
                "yes_price": yes_c / 100.0,
            })


async def sentiment_handler(tick, news_client):
    """Integrate news sentiment into yes_price stream."""
    headline = f"{tick['ticker']} 15m crypto"
    news = news_client.get_sentiment(headline)
    tick["news_score"] = news.get("score", 0.0)
    # publish into your StreamingBus / SentimentBus here


async def stream_yes_with_news(news_client, tickers: List[str] = None):
    """Stream yes prices with integrated news sentiment."""
    async def _handler(tick):
        await sentiment_handler(tick, news_client)
    await stream_yes_prices(_handler, tickers)


# ── Simplified Historical Data ─────────────────────────────────────────

def get_yes_price_series(ticker: str, start_iso: str, end_iso: str) -> List[Dict[str, Any]]:
    """Get sorted yes price series for backtesting."""
    out, cursor = [], None
    while True:
        params = {
            "ticker": ticker,
            "start_time": start_iso,
            "end_time": end_iso,
            "limit": 500,
        }
        if cursor:
            params["cursor"] = cursor
        r = requests.get(f"{BASE_URL}/trades", params=params, timeout=5)
        r.raise_for_status()
        data = r.json()
        for tr in data["trades"]:
            out.append({
                "ts": tr["created_time"],
                "yes_price_c": tr["yes_price"],
            })
        cursor = data.get("cursor")
        if not cursor:
            break
    return sorted(out, key=lambda x: x["ts"])


# ── Simplified Backtesting ─────────────────────────────────────────────

def backtest_yes_momentum(series: List[Dict[str, Any]], threshold_c: int = 3) -> List[Dict[str, Any]]:
    """Backtest 15m momentum strategy on yes price series."""
    series = sorted(series, key=lambda x: x["ts"])
    results = []
    for i in range(2, len(series)):
        t0 = parse_ts(series[i]["ts"])
        p0 = series[i]["yes_price_c"]
        p1 = series[i-1]["yes_price_c"]
        p2 = series[i-2]["yes_price_c"]

        up = p0 - p1 > threshold_c and p1 - p2 > 0
        down = p1 - p0 > threshold_c and p2 - p1 > 0
        if not (up or down):
            continue

        direction = 1 if up else -1
        exit_time = t0 + timedelta(minutes=15)
        exit_tick = next((x for x in series if parse_ts(x["ts"]) >= exit_time), None)
        if not exit_tick:
            continue
        p_exit = exit_tick["yes_price_c"]
        pnl_c = direction * (p_exit - p0)

        results.append({
            "entry_ts": t0.isoformat(),
            "exit_ts": exit_time.isoformat(),
            "dir": direction,
            "entry_c": p0,
            "exit_c": p_exit,
            "pnl_c": pnl_c,
        })
    return results


# ── Orderbook Microstructure ─────────────────────────────────────────────

class LocalBook:
    """Local orderbook for maker bot optimization."""
    
    def __init__(self):
        self.yes = {}  # price_c -> size
        self.no = {}

    def apply_snapshot(self, ob: Dict[str, Any]):
        self.yes = {p: q for p, q in ob["yes"]}
        self.no = {p: q for p, q in ob["no"]}

    def best_yes(self):
        return max(self.yes.items()) if self.yes else (None, 0)

    def best_no(self):
        return max(self.no.items()) if self.no else (None, 0)

    def get_microstructure(self):
        yes_price_c, yes_size = self.best_yes()
        no_price_c, no_size = self.best_no()
        
        if yes_price_c is not None and no_price_c is not None:
            yes_bid = yes_price_c / 100.0
            yes_ask = (100 - no_price_c) / 100.0
            spread_c = (yes_ask - yes_bid) * 100
        else:
            yes_bid = yes_ask = spread_c = None
        
        return {
            "yes_bid_c": yes_price_c,
            "yes_ask_c": 100 - no_price_c if no_price_c is not None else None,
            "yes_bid": yes_bid,
            "yes_ask": yes_ask,
            "spread_cents": spread_c,
            "yes_depth": yes_size,
            "no_depth": no_size,
        }


async def orderbook_stream(tickers: List[str], handler):
    """Stream orderbook data for maker bot optimization."""
    headers = {
        "KALSHI-ACCESS-KEY": os.getenv("KALSHI_API_KEY"),
        "KALSHI-ACCESS-SIGNATURE": os.getenv("KALSHI_API_SIGNATURE"),
        "KALSHI-ACCESS-TIMESTAMP": os.getenv("KALSHI_API_TS"),
    }
    
    async with websockets.connect(WS_URL, additional_headers=headers) as ws:
        sub = {"type": "subscribe", "channels": [{"name": "orderbook", "symbols": tickers}]}
        await ws.send(json.dumps(sub))
        books = {t: LocalBook() for t in tickers}
        async for raw in ws:
            msg = json.loads(raw)
            if msg.get("type") != "orderbook":
                continue
            ob = msg["orderbook"]
            t = msg["ticker"]
            books[t].apply_snapshot(ob)
            await handler(t, books[t])


# ── Profitability Analysis ─────────────────────────────────────────────

def analyze_momentum_profitability(results: List[Dict[str, Any]], 
                                   contract_size: float = 1.0,
                                   fee_per_contract: float = 0.04) -> Dict[str, Any]:
    """
    Analyze profitability of momentum strategy.
    
    Args:
        results: Backtest results with pnl_c in cents
        contract_size: Number of contracts per trade
        fee_per_contract: Kalshi fee per contract in dollars
    """
    if not results:
        return {"error": "No trades to analyze"}
    
    # Convert PnL to dollars and subtract fees
    total_pnl_dollars = sum(r["pnl_c"] / 100.0 * contract_size for r in results)
    total_fees = len(results) * 2 * fee_per_contract * contract_size  # entry + exit fees
    net_pnl = total_pnl_dollars - total_fees
    
    # Calculate statistics
    wins = [r for r in results if r["pnl_c"] > 0]
    losses = [r for r in results if r["pnl_c"] < 0]
    
    win_rate = len(wins) / len(results) if results else 0
    avg_win = sum(r["pnl_c"] for r in wins) / len(wins) if wins else 0
    avg_loss = sum(r["pnl_c"] for r in losses) / len(losses) if losses else 0
    
    # Calculate running drawdown
    equity_curve = []
    running_pnl = 0
    for r in results:
        running_pnl += (r["pnl_c"] / 100.0 * contract_size) - (2 * fee_per_contract * contract_size)
        equity_curve.append(running_pnl)
    
    peak = max(equity_curve) if equity_curve else 0
    drawdown = peak - min(equity_curve) if equity_curve else 0
    max_drawdown_pct = (drawdown / peak * 100) if peak > 0 else 0
    
    return {
        "total_trades": len(results),
        "total_pnl_dollars": total_pnl_dollars,
        "total_fees": total_fees,
        "net_pnl": net_pnl,
        "win_rate": win_rate,
        "avg_win_cents": avg_win,
        "avg_loss_cents": avg_loss,
        "max_drawdown_dollars": drawdown,
        "max_drawdown_pct": max_drawdown_pct,
        "profit_factor": abs(avg_win / avg_loss) if avg_loss != 0 else float('inf'),
        "sharpe_ratio": (net_pnl / len(results)) / (drawdown / len(results)) if drawdown > 0 else 0,
    }


# ── Complete Production Pipeline ───────────────────────────────────────

async def complete_production_pipeline(news_client):
    """
    Complete production pipeline:
    1. Stream real-time yes prices with news sentiment
    2. Maintain orderbook for maker decisions
    3. Backtest historical momentum strategies
    4. Analyze profitability
    """
    
    # 1. Historical backtesting
    tickers = ["KXBTC15M-25MAR26", "KXETH15M-25MAR26"]  # example market tickers
    end_time = datetime.now(timezone.utc)
    start_time = end_time - timedelta(days=7)
    
    all_results = []
    for ticker in tickers:
        series = get_yes_price_series(ticker, start_time.isoformat(), end_time.isoformat())
        results = backtest_yes_momentum(series, threshold_c=3)
        all_results.extend(results)
        print(f"{ticker}: {len(results)} trades")
    
    # 2. Profitability analysis
    analysis = analyze_momentum_profitability(all_results)
    print(f"Analysis: {analysis}")
    
    # 3. Real-time streaming with news
    async def trade_handler(tick):
        print(f"Trade: {tick['ticker']} @ {tick['yes_price']:.3f} (news: {tick.get('news_score', 0):.2f})")
        # Here you would:
        # - Update momentum calculations
        # - Check against orderbook for execution
        # - Execute trades if conditions met
    
    # 4. Orderbook maintenance for maker decisions
    async def orderbook_handler(ticker, book):
        micro = book.get_microstructure()
        if micro["spread_cents"]:
            print(f"{ticker}: spread={micro['spread_cents']}¢ bid={micro['yes_bid']:.3f} ask={micro['yes_ask']:.3f}")
            # Here you would:
            # - Check if spread is profitable for market making
            # - Calculate optimal bid/ask prices
            # - Pass to ExecutionIntelligence.decide(...)
    
    # Start both streams
    await asyncio.gather(
        stream_yes_with_news(news_client, tickers),
        orderbook_stream(tickers, orderbook_handler)
    )


# ── Updated Convenience Functions ───────────────────────────────────────

# Convenience functions
def fetch_15m_crypto_markets(min_volume_usd: float = 2000) -> List[KalshiMarket]:
    """Convenience function to fetch 15m crypto markets."""
    client = get_kalshi_market_client()
    markets = client.fetch_15m_crypto_markets()
    return client.filter_high_volume_markets(markets, min_volume_usd)


def build_kalshi_sentiment_config(min_volume_usd: float = 2000) -> Dict[str, Dict[str, Any]]:
    """Convenience function to build sentiment config."""
    builder = KalshiSentimentConfigBuilder()
    return builder.build_kalshi_sentiment_config(min_volume_usd)


# ── Complete Usage Example ───────────────────────────────────────────────

def example_complete_pipeline():
    """
    Complete example of Kalshi-driven sentiment analysis pipeline.
    
    This demonstrates:
    1. Fetching crypto markets with pagination
    2. Computing momentum signals
    3. Enriching with news sentiment
    4. Building agent views for trading
    5. Simple backtesting
    """
    
    # 1. Get Kalshi client and fetch markets
    client = get_kalshi_market_client()
    markets_data = client.get_all_crypto_markets(status="open")
    print(f"Fetched {len(markets_data)} total crypto markets")
    
    # Convert to KalshiMarket objects
    markets = client.fetch_crypto_markets(status="open")
    
    # Filter to 15m markets with volume
    markets_15m = [m for m in markets if "15 minutes" in m.title]
    high_volume = client.filter_high_volume_markets(markets_15m, min_volume_usd=2000)
    print(f"Found {len(high_volume)} high-volume 15m markets")
    
    # 2. Compute momentum signals
    momentum_calc = YesMomentum(window=4)
    momentum_signals = compute_15m_momentum(
        [m.__dict__ for m in high_volume], 
        momentum_calc
    )
    print(f"Computed {len(momentum_signals)} momentum signals")
    
    # 3. Enrich with news sentiment (mock news client for example)
    class MockNewsClient:
        def get_sentiment(self, headline: str) -> Dict[str, float]:
            # Mock sentiment based on headline keywords
            if any(word in headline.upper() for word in ["BTC", "BITCOIN"]):
                return {"score": 0.3, "volume": 100}
            elif any(word in headline.upper() for word in ["ETH", "ETHEREUM"]):
                return {"score": -0.2, "volume": 80}
            return {"score": 0.0, "volume": 50}
    
    news_client = MockNewsClient()
    enriched_markets = enrich_crypto_markets_with_news(
        [m.__dict__ for m in high_volume], 
        news_client
    )
    print(f"Enriched {len(enriched_markets)} markets with news sentiment")
    
    # 4. Build agent views for trading decisions
    agent_views = []
    for market in high_volume[:5]:  # First 5 markets
        view = build_agent_view(market, client)
        agent_views.append(view)
        print(f"{market.ticker}: bid={view.get('yes_bid'):.3f}, ask={view.get('yes_ask'):.3f}, spread={view.get('spread_cents')}¢")
    
    # 5. Simple backtesting example
    # Mock price series for backtesting
    import time
    now = int(time.time())
    
    # Generate mock price data
    price_series = [
        {"ts": now - 1800, "yes_price_c": 4800},  # 30 min ago
        {"ts": now - 900, "yes_price_c": 4900},   # 15 min ago
        {"ts": now, "yes_price_c": 5000},         # now
    ]
    
    # Mock sentiment series
    sentiment_series = [
        {"ts": now - 900, "score": 0.5},  # Positive sentiment 15 min ago
    ]
    
    # Run backtest
    backtest_results = backtest_sentiment(price_series, sentiment_series, horizon_secs=900)
    print(f"Backtest results: {len(backtest_results)} trades")
    for result in backtest_results:
        print(f"  PnL: {result['pnl_c']}¢, direction: {result['dir']}")
    
    return {
        "markets_count": len(high_volume),
        "momentum_signals": len(momentum_signals),
        "enriched_markets": len(enriched_markets),
        "agent_views": len(agent_views),
        "backtest_results": len(backtest_results)
    }


if __name__ == "__main__":
    # Run the complete example
    results = example_complete_pipeline()
    print(f"\nPipeline complete: {results}")
