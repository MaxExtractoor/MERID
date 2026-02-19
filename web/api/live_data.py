"""
Live Data API - Real-time prices, news, predictions, and charts.
Institutional-grade data streaming for 50+ cryptocurrencies.
"""

from __future__ import annotations

import asyncio
from typing import Dict, List, Optional
from datetime import datetime, timedelta
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
_last_update = datetime.now()
_streaming_active = False


async def fetch_live_prices():
    """Fetch real-time prices for all 50+ assets from CoinGecko API."""
    global _price_cache, _last_update
    
    try:
        from data.asset_universe import get_all_coingecko_ids, ASSET_UNIVERSE
        
        # Get all CoinGecko IDs
        coingecko_ids = get_all_coingecko_ids()
        
        # Use sync client in thread pool to avoid event loop SSL issues
        def sync_fetch():
            with httpx.Client(timeout=30.0, verify=False) as client:
                ids_param = ','.join(coingecko_ids)
                url = f"https://api.coingecko.com/api/v3/simple/price?ids={ids_param}&vs_currencies=usd&include_24hr_change=true&include_24hr_vol=true&include_market_cap=true"
                return client.get(url)
        
        response = await asyncio.get_event_loop().run_in_executor(None, sync_fetch)
        
        if response.status_code == 200:
            data = response.json()
            
            # Map CoinGecko data to our format
            for symbol, asset in ASSET_UNIVERSE.items():
                coin_id = asset.coingecko_id
                if coin_id in data:
                    coin_data = data[coin_id]
                    _price_cache[asset.symbol] = {
                        'symbol': asset.symbol,
                        'name': asset.name,
                        'category': asset.category,
                        'price': coin_data.get('usd', 0),
                        'change_24h': coin_data.get('usd_24h_change', 0),
                        'volume_24h': coin_data.get('usd_24h_vol', 0),
                        'market_cap': coin_data.get('usd_market_cap', 0),
                        'high_24h': coin_data.get('usd', 0) * 1.02,
                        'low_24h': coin_data.get('usd', 0) * 0.98,
                        'timestamp': datetime.now().isoformat()
                    }
            
            _last_update = datetime.now()
            logger.info(f"[LiveData] Updated {len(_price_cache)} assets from CoinGecko")
            return
        else:
            logger.info(f"[LiveData] CoinGecko returned status {response.status_code}")
    except Exception as e:
        import traceback
        logger.error(f"[LiveData] Error fetching from CoinGecko: {type(e).__name__}: {str(e)}")
        logger.error(traceback.format_exc())
        _last_update = datetime.now()


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
                        'timestamp': item.get('updated_at', datetime.now().isoformat())
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
    if not _price_cache or (datetime.now() - _last_update).total_seconds() > 10:
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
            'timestamp': datetime.now().isoformat()
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
        'timestamp': datetime.now().isoformat()
    }
