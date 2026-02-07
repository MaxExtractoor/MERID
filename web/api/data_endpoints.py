"""
Data Endpoints API for MERID.

Provides real market data for charts and analysis.
"""

from __future__ import annotations

from typing import Optional, List
from fastapi import APIRouter, HTTPException

from data.live_price_feed import get_live_price_feed
from utils.logger import get_logger

router = APIRouter(prefix="/api/v1/data", tags=["data"])
logger = get_logger("web.api.data_endpoints")


@router.get("/ohlcv")
async def get_ohlcv_data(
    symbol: str = "BTC/USDT",
    timeframe: str = "1h",
    limit: int = 100
):
    """
    Get OHLCV (candlestick) data for charting.
    
    Args:
        symbol: Trading pair (e.g., BTC/USDT)
        timeframe: Candle timeframe (1m, 5m, 15m, 1h, 4h, 1d)
        limit: Number of candles to return
    """
    price_feed = get_live_price_feed()
    
    try:
        ohlcv = await price_feed.fetch_historical_ohlcv(symbol, timeframe, limit)
        
        if not ohlcv:
            raise HTTPException(status_code=404, detail="No data available")
        
        # Format for LightweightCharts
        formatted_data = [
            {
                "time": candle[0] / 1000,  # Convert to seconds
                "open": candle[1],
                "high": candle[2],
                "low": candle[3],
                "close": candle[4],
                "volume": candle[5]
            }
            for candle in ohlcv
        ]
        
        return {
            "symbol": symbol,
            "timeframe": timeframe,
            "data": formatted_data,
            "count": len(formatted_data)
        }
        
    except Exception as exc:
        logger.error(f"Failed to fetch OHLCV data: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/price/{symbol}")
async def get_current_price(symbol: str):
    """Get current price for a symbol."""
    price_feed = get_live_price_feed()
    
    # Ensure symbol has /USDT suffix
    if '/' not in symbol:
        symbol = f"{symbol}/USDT"
    
    price_data = price_feed.get_current_price(symbol)
    
    if not price_data:
        raise HTTPException(status_code=404, detail=f"Price data not available for {symbol}")
    
    return {
        "symbol": symbol,
        "price": price_data.price,
        "bid": price_data.bid,
        "ask": price_data.ask,
        "volume_24h": price_data.volume_24h,
        "change_24h_pct": price_data.change_24h_pct,
        "timestamp": price_data.timestamp.isoformat(),
        "exchange": price_data.exchange
    }


@router.get("/prices")
async def get_all_prices():
    """Get current prices for all tracked symbols."""
    price_feed = get_live_price_feed()
    
    all_prices = price_feed.get_all_prices()
    
    return {
        "prices": {
            symbol: {
                "price": data.price,
                "change_24h_pct": data.change_24h_pct,
                "volume_24h": data.volume_24h,
                "timestamp": data.timestamp.isoformat()
            }
            for symbol, data in all_prices.items()
        },
        "count": len(all_prices)
    }
