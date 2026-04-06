"""
Live Data API - Real-time prices, news, predictions, and charts.
Institutional-grade data streaming for 50+ cryptocurrencies.
"""

from __future__ import annotations

import asyncio
from typing import Dict, List, Optional
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, HTTPException, Query
import httpx

from utils.deps import get_ccxt

import logging
logger = logging.getLogger("live_data")

router = APIRouter(prefix="/api/v1/live", tags=["live"])


# Global cache for live data
_price_cache: Dict[str, dict] = {}
_news_cache: List[dict] = []
_predictions_cache: List[dict] = []
_last_update = datetime.now(timezone.utc)
_streaming_active = False


# Kalshi crypto assets that must show Coinbase spot prices (Kalshi's reference exchange).
# Prices for these symbols are fetched from Coinbase first; CoinGecko fills the rest.
_KALSHI_CRYPTO_SYMBOLS = {"BTC", "ETH", "SOL", "XRP", "DOGE"}

# Coinbase spot endpoint for a single symbol: GET /v2/prices/{SYM}-USD/spot
_COINBASE_SPOT_URL = "https://api.coinbase.com/v2/prices/{sym}-USD/spot"


# Multipliers for synthetic 24-hour high/low estimates (absent from the CoinGecko endpoint
# we use).  ±2% is a rough placeholder; replace with real OHLCV data if precision matters.
_HIGH_24H_MULTIPLIER = 1.02
_LOW_24H_MULTIPLIER = 0.98


def _fetch_coinbase_spot_prices() -> Dict[str, float]:
    """Fetch spot prices for the 5 Kalshi crypto assets from Coinbase (synchronous).

    Returns a dict of ``{symbol: price}`` for whichever symbols succeeded.
    Failures are logged and silently skipped so the caller can fall back to
    CoinGecko for any missing symbols.
    """
    prices: Dict[str, float] = {}
    with httpx.Client(timeout=5.0) as client:
        for sym in _KALSHI_CRYPTO_SYMBOLS:
            try:
                resp = client.get(_COINBASE_SPOT_URL.format(sym=sym))
                if resp.status_code == 200:
                    amount = resp.json().get("data", {}).get("amount")
                    if amount:
                        prices[sym] = float(amount)
                        logger.debug("[LiveData] Coinbase spot %s=%.4f", sym, prices[sym])
                else:
                    logger.warning(
                        "[LiveData] Coinbase returned HTTP %d for %s", resp.status_code, sym
                    )
            except Exception as exc:
                logger.warning("[LiveData] Coinbase spot fetch failed for %s: %s", sym, exc)
    return prices


async def fetch_live_prices():
    """Fetch real-time prices for all tracked assets.

    Price source strategy (aligns UI with Kalshi's reference exchange):
      1. Coinbase (PRIMARY) — for the 5 Kalshi crypto assets (BTC/ETH/SOL/XRP/DOGE).
         Kalshi uses Coinbase as their index reference; using the same source keeps
         our displayed price aligned with contract strike prices.
      2. CoinGecko (SECONDARY) — for all remaining assets, plus any Kalshi assets
         where Coinbase is temporarily unavailable.
    """
    global _price_cache, _last_update
    
    # ── Step 1: Coinbase prices for the 5 Kalshi assets ───────────────────
    def sync_coinbase():
        return _fetch_coinbase_spot_prices()

    coinbase_prices: Dict[str, float] = {}
    try:
        coinbase_prices = await asyncio.get_running_loop().run_in_executor(
            None, sync_coinbase
        )
        if coinbase_prices:
            logger.info(
                "[LiveData] Coinbase spot prices fetched for: %s",
                ", ".join(f"{s}={p}" for s, p in sorted(coinbase_prices.items())),
            )
    except Exception as exc:
        logger.error("[LiveData] Coinbase bulk fetch failed: %s", exc)

    # ── Step 2: CoinGecko for everything else (and fallback for missed assets) ─
    try:
        from data.asset_universe import get_all_coingecko_ids, ASSET_UNIVERSE
        
        coingecko_ids = get_all_coingecko_ids()
        
        def sync_coingecko():
            with httpx.Client(timeout=30.0) as client:
                ids_param = ','.join(coingecko_ids)
                url = (
                    f"https://api.coingecko.com/api/v3/simple/price"
                    f"?ids={ids_param}&vs_currencies=usd"
                    f"&include_24hr_change=true&include_24hr_vol=true&include_market_cap=true"
                )
                return client.get(url)
        
        response = await asyncio.get_running_loop().run_in_executor(None, sync_coingecko)
        
        if response.status_code == 200:
            data = response.json()
            
            for symbol, asset in ASSET_UNIVERSE.items():
                coin_id = asset.coingecko_id
                if coin_id not in data:
                    continue
                coin_data = data[coin_id]
                cg_price = coin_data.get('usd', 0)

                # For Kalshi crypto assets: prefer Coinbase price; fall back to
                # CoinGecko only if Coinbase was unavailable for this symbol.
                if asset.symbol in _KALSHI_CRYPTO_SYMBOLS:
                    display_price = coinbase_prices.get(asset.symbol, cg_price)
                    if asset.symbol not in coinbase_prices:
                        logger.warning(
                            "[LiveData] %s: Coinbase unavailable — using CoinGecko fallback "
                            "(price=%.4f). This may diverge from Kalshi reference.",
                            asset.symbol, cg_price,
                        )
                else:
                    display_price = cg_price

                _price_cache[asset.symbol] = {
                    'symbol': asset.symbol,
                    'name': asset.name,
                    'category': asset.category,
                    'price': display_price,
                    'change_24h': coin_data.get('usd_24h_change', 0),
                    'volume_24h': coin_data.get('usd_24h_vol', 0),
                    'market_cap': coin_data.get('usd_market_cap', 0),
                    'high_24h': display_price * _HIGH_24H_MULTIPLIER,
                    'low_24h': display_price * _LOW_24H_MULTIPLIER,
                    'price_source': (
                        'coinbase' if asset.symbol in coinbase_prices else 'coingecko'
                    ),
                    'timestamp': datetime.now(timezone.utc).isoformat()
                }
            
            _last_update = datetime.now(timezone.utc)
            kalshi_sources = {
                s: _price_cache[s].get('price_source', '?')
                for s in _KALSHI_CRYPTO_SYMBOLS
                if s in _price_cache
            }
            logger.info(
                "[LiveData] Updated %d assets. Kalshi crypto price sources: %s",
                len(_price_cache),
                kalshi_sources,
            )
            return
        else:
            logger.info(f"[LiveData] CoinGecko returned status {response.status_code}")
    except Exception as e:
        import traceback
        logger.error(f"[LiveData] Error fetching from CoinGecko: {type(e).__name__}: {str(e)}")
        logger.error(traceback.format_exc())

    # If CoinGecko also failed but we got Coinbase prices, at least update those.
    if coinbase_prices:
        for sym, price in coinbase_prices.items():
            if sym in _price_cache:
                _price_cache[sym]['price'] = price
                _price_cache[sym]['price_source'] = 'coinbase'
            # If symbol not yet in cache (e.g. very first call with CoinGecko down),
            # leave it absent rather than creating a partial entry.

    _last_update = datetime.now(timezone.utc)



async def fetch_crypto_news():
    """Fetch latest crypto news."""
    global _news_cache
    
    try:
        # Using CoinGecko news API (free)
        async with httpx.AsyncClient(timeout=15.0, verify=False) as client:
            url = "https://api.coingecko.com/api/v3/news"
            response = await client.get(url)
            if response.status_code == 200:
                data = response.json()
                _news_cache = [
                    {
                        'title': item.get('title', 'No title'),
                        'description': item.get('description', '')[:200],
                        'url': item.get('url', ''),
                        'source': item.get('author', 'Unknown'),
                        'timestamp': item.get('updated_at', datetime.now(timezone.utc).isoformat())
                    }
                    for item in data.get('data', [])[:10]
                ]
                logger.info(f"[LiveData] Fetched {len(_news_cache)} news items")
    except Exception as e:
        logger.error(f"[LiveData] Error fetching news: {e}")
        _news_cache = []


async def fetch_prediction_markets():
    """Fetch prediction market data from Kalshi."""
    global _predictions_cache
    
    try:
        # Import Kalshi aggregator to get real markets
        from monitoring.prediction_markets import get_prediction_aggregator
        aggregator = get_prediction_aggregator()
        
        # Get markets from Kalshi aggregator
        kalshi_markets = aggregator.get_all_markets()
        _predictions_cache = [
            {
                'question': market.question,
                'yes_price': market.yes_price,
                'no_price': market.no_price,
                'volume': market.volume_24h,
                'end_date': datetime.fromtimestamp(market.resolution_date).isoformat() if market.resolution_date else '',
                'market_id': market.market_id
            }
            for market_id, market in list(kalshi_markets.items())[:10]
        ]
        logger.info(f"[LiveData] Fetched {len(_predictions_cache)} Kalshi prediction markets")
    except Exception as e:
        logger.error(f"Error fetching predictions: {e}")
        # Don't use fallback - let frontend handle empty data
        _predictions_cache = []


@router.get("/prices")
async def get_live_prices(
    category: Optional[str] = Query(None, description="Filter by category: layer1, layer2, defi, meme, gaming, ai, privacy, infrastructure"),
    market_cap_tier: Optional[str] = Query(None, description="Filter by market cap: large_cap, mid_cap, small_cap"),
    limit: Optional[int] = Query(None, description="Limit number of results"),
    sort_by: Optional[str] = Query("market_cap", description="Sort by: market_cap, volume, change_24h, price")
):
    """Get current live prices for all tracked assets with filtering."""
    # Update if cache is stale (older than 10 seconds)
    if not _price_cache or (datetime.now(timezone.utc) - _last_update).total_seconds() > 10:
        await fetch_live_prices()
    
    prices = dict(_price_cache)
    
    # Apply category filter
    if category:
        from data.asset_universe import CATEGORIES
        if category in CATEGORIES:
            allowed_symbols = [f"{s}/USDT" for s in CATEGORIES[category]]
            prices = {k: v for k, v in prices.items() if k in allowed_symbols}
    
    # Apply market cap tier filter
    if market_cap_tier:
        from data.asset_universe import MARKET_CAP_TIERS
        if market_cap_tier in MARKET_CAP_TIERS:
            allowed_symbols = [f"{s}/USDT" for s in MARKET_CAP_TIERS[market_cap_tier]]
            prices = {k: v for k, v in prices.items() if k in allowed_symbols}
    
    # Sort results
    if sort_by == 'market_cap':
        prices = dict(sorted(prices.items(), key=lambda x: x[1].get('market_cap', 0), reverse=True))
    elif sort_by == 'volume':
        prices = dict(sorted(prices.items(), key=lambda x: x[1].get('volume_24h', 0), reverse=True))
    elif sort_by == 'change_24h':
        prices = dict(sorted(prices.items(), key=lambda x: x[1].get('change_24h', 0), reverse=True))
    elif sort_by == 'price':
        prices = dict(sorted(prices.items(), key=lambda x: x[1].get('price', 0), reverse=True))
    
    # Apply limit
    if limit:
        prices = dict(list(prices.items())[:limit])
    
    return {
        'status': 'success',
        'prices': prices,
        'last_update': _last_update.isoformat(),
        'count': len(prices),
        'total_assets': len(_price_cache),
        'filters': {
            'category': category,
            'market_cap_tier': market_cap_tier,
            'sort_by': sort_by,
            'limit': limit
        }
    }


@router.get("/price/{symbol}")
async def get_single_price(symbol: str):
    """Get price for a specific symbol."""
    if not _price_cache:
        await fetch_live_prices()
    
    # Normalize symbol
    if '/' not in symbol:
        symbol = f"{symbol.upper()}/USDT"
    
    if symbol not in _price_cache:
        raise HTTPException(status_code=404, detail=f"Symbol {symbol} not found")
    
    return {
        'status': 'success',
        'data': _price_cache[symbol]
    }


@router.get("/news")
async def get_crypto_news():
    """Get latest cryptocurrency news."""
    if not _news_cache:
        await fetch_crypto_news()
    
    return {
        'status': 'success',
        'news': _news_cache,
        'count': len(_news_cache)
    }


@router.get("/predictions")
async def get_prediction_markets():
    """Get active prediction markets."""
    if not _predictions_cache:
        await fetch_prediction_markets()
    
    return {
        'status': 'success',
        'markets': _predictions_cache,
        'count': len(_predictions_cache)
    }


@router.get("/chart/{symbol}")
async def get_chart_data(
    symbol: str,
    timeframe: str = "1h",
    limit: int = 100
):
    """Get OHLCV chart data for a symbol."""
    ccxt = get_ccxt()
    if not ccxt:
        raise HTTPException(status_code=503, detail="Charting unavailable: ccxt not installed")

    try:
        # Try Kraken first (no geo-restrictions)
        exchange = ccxt.kraken({'enableRateLimit': True})
        
        # Normalize symbol
        if '/' not in symbol:
            symbol = f"{symbol.upper()}/USDT"
        
        try:
            # Fetch OHLCV data
            ohlcv = exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
            
            # Format for charts
            chart_data = [
                {
                    'time': candle[0] / 1000,  # Convert to seconds
                    'open': candle[1],
                    'high': candle[2],
                    'low': candle[3],
                    'close': candle[4],
                    'volume': candle[5]
                }
                for candle in ohlcv
            ]
            
            return {
                'status': 'success',
                'symbol': symbol,
                'timeframe': timeframe,
                'data': chart_data,
                'count': len(chart_data)
            }
        except Exception as chart_error:
            # No fallback - return error
            raise HTTPException(status_code=500, detail=f"Failed to fetch chart data: {str(chart_error)}")
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/categories")
async def get_categories():
    """Get all available asset categories."""
    from data.asset_universe import CATEGORIES, MARKET_CAP_TIERS
    
    return {
        'status': 'success',
        'categories': {
            'by_type': list(CATEGORIES.keys()),
            'by_market_cap': list(MARKET_CAP_TIERS.keys())
        },
        'category_counts': {
            cat: len(symbols) for cat, symbols in CATEGORIES.items()
        }
    }


@router.get("/watchlist")
async def get_watchlist():
    """Get default watchlist (top 20 by market cap)."""
    from data.asset_universe import get_watchlist_symbols
    
    if not _price_cache:
        await fetch_live_prices()
    
    watchlist_symbols = get_watchlist_symbols()
    watchlist_prices = {k: v for k, v in _price_cache.items() if k in watchlist_symbols}
    
    return {
        'status': 'success',
        'watchlist': watchlist_prices,
        'count': len(watchlist_prices)
    }


@router.get("/market/overview")
async def get_market_overview():
    """Get market overview with aggregated statistics."""
    if not _price_cache:
        await fetch_live_prices()
    
    # Calculate market statistics
    total_market_cap = sum(p.get('market_cap', 0) for p in _price_cache.values())
    total_volume = sum(p.get('volume_24h', 0) for p in _price_cache.values())
    
    gainers = sorted(_price_cache.items(), key=lambda x: x[1].get('change_24h', 0), reverse=True)[:10]
    losers = sorted(_price_cache.items(), key=lambda x: x[1].get('change_24h', 0))[:10]
    
    avg_change = sum(p.get('change_24h', 0) for p in _price_cache.values()) / len(_price_cache) if _price_cache else 0
    
    return {
        'status': 'success',
        'overview': {
            'total_market_cap': total_market_cap,
            'total_volume_24h': total_volume,
            'average_change_24h': avg_change,
            'assets_tracked': len(_price_cache),
            'top_gainers': [{'symbol': k, **v} for k, v in gainers],
            'top_losers': [{'symbol': k, **v} for k, v in losers],
            'timestamp': datetime.now(timezone.utc).isoformat()
        }
    }


@router.get("/refresh")
async def refresh_all_data():
    """Force refresh all live data."""
    await asyncio.gather(
        fetch_live_prices(),
        fetch_crypto_news(),
        fetch_prediction_markets()
    )
    
    return {
        'status': 'success',
        'message': 'All data refreshed',
        'assets_updated': len(_price_cache),
        'timestamp': datetime.now(timezone.utc).isoformat()
    }
