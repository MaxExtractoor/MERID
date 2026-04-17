"""
Markets Data API - Stocks, Forex, Commodities

Provides REST endpoints for all market data types:
- Stocks/Equities
- Forex/Fiat currencies
- Commodities/Metals
- Live prices and historical data
"""

from typing import Dict, List, Any, Optional
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from data.stocks_feed import get_stocks_feed
from data.forex_feed import get_forex_feed
from data.commodities_feed import get_commodities_feed
from utils.logger import get_logger

logger = get_logger("web.api.markets_data")

router = APIRouter(prefix="/api/v1/markets", tags=["markets"])


class StockPriceResponse(BaseModel):
    """Stock price response model."""
    symbol: str
    price: float
    bid: float
    ask: float
    volume: float
    change_pct: float
    timestamp: int
    source: str
    market_cap: Optional[float] = None
    pe_ratio: Optional[float] = None


class ForexRateResponse(BaseModel):
    """Forex rate response model."""
    pair: str
    rate: float
    bid: float
    ask: float
    timestamp: int
    source: str


class CommodityPriceResponse(BaseModel):
    """Commodity price response model."""
    symbol: str
    name: str
    price: float
    unit: str
    change_pct: float
    timestamp: int
    source: str


@router.options("/stocks")
async def options_stocks():
    """Handle OPTIONS preflight for CORS."""
    return {}


@router.get("/stocks")
async def get_stocks(
    symbols: Optional[str] = Query(None, description="Comma-separated list of stock symbols")
) -> Dict[str, Any]:
    """
    Get live stock prices.
    
    Query params:
    - symbols: Optional comma-separated list (e.g., "AAPL,TSLA,NVDA")
    
    Returns all tracked stocks if no symbols specified.
    """
    try:
        stocks_feed = get_stocks_feed()
        all_prices = stocks_feed.get_latest_prices()
        
        # Filter by symbols if provided
        if symbols:
            symbol_list = [s.strip().upper() for s in symbols.split(',')]
            filtered_prices = {k: v for k, v in all_prices.items() if k in symbol_list}
        else:
            filtered_prices = all_prices
        
        # Convert to response format
        stocks_data = []
        for symbol, price_data in filtered_prices.items():
            stocks_data.append({
                "symbol": symbol,
                "price": price_data.price,
                "bid": price_data.bid,
                "ask": price_data.ask,
                "volume": price_data.volume,
                "change_pct": price_data.change_pct,
                "timestamp": int(price_data.timestamp.timestamp() * 1000),
                "source": price_data.source,
                "market_cap": price_data.market_cap,
                "pe_ratio": price_data.pe_ratio
            })
        
        return {
            "stocks": stocks_data,
            "count": len(stocks_data),
            "timestamp": int(stocks_feed.get_latest_prices()[list(stocks_feed.get_latest_prices().keys())[0]].timestamp.timestamp() * 1000) if stocks_data else 0
        }
        
    except Exception as e:
        logger.error(f"Failed to get stocks: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.options("/forex")
async def options_forex():
    """Handle OPTIONS preflight for CORS."""
    return {}


@router.get("/forex")
async def get_forex(
    pairs: Optional[str] = Query(None, description="Comma-separated list of currency pairs")
) -> Dict[str, Any]:
    """
    Get live forex rates.
    
    Query params:
    - pairs: Optional comma-separated list (e.g., "EUR/USD,GBP/USD")
    
    Returns all tracked pairs if no pairs specified.
    """
    try:
        forex_feed = get_forex_feed()
        all_rates = forex_feed.get_latest_rates()
        
        # Filter by pairs if provided
        if pairs:
            pair_list = [p.strip().upper() for p in pairs.split(',')]
            filtered_rates = {k: v for k, v in all_rates.items() if k in pair_list}
        else:
            filtered_rates = all_rates
        
        # Convert to response format
        forex_data = []
        for pair, rate_data in filtered_rates.items():
            forex_data.append({
                "pair": pair,
                "rate": rate_data.rate,
                "bid": rate_data.bid,
                "ask": rate_data.ask,
                "timestamp": int(rate_data.timestamp.timestamp() * 1000),
                "source": rate_data.source
            })
        
        return {
            "forex": forex_data,
            "count": len(forex_data),
            "timestamp": int(forex_feed.get_latest_rates()[list(forex_feed.get_latest_rates().keys())[0]].timestamp.timestamp() * 1000) if forex_data else 0
        }
        
    except Exception as e:
        logger.error(f"Failed to get forex: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.options("/commodities")
async def options_commodities():
    """Handle OPTIONS preflight for CORS."""
    return {}


@router.get("/commodities")
async def get_commodities(
    symbols: Optional[str] = Query(None, description="Comma-separated list of commodity symbols")
) -> Dict[str, Any]:
    """
    Get live commodity prices.
    
    Query params:
    - symbols: Optional comma-separated list (e.g., "XAU/USD,WTI,BRENT")
    
    Returns all tracked commodities if no symbols specified.
    """
    try:
        commodities_feed = get_commodities_feed()
        all_prices = commodities_feed.get_latest_prices()
        
        # Filter by symbols if provided
        if symbols:
            symbol_list = [s.strip().upper() for s in symbols.split(',')]
            filtered_prices = {k: v for k, v in all_prices.items() if k in symbol_list}
        else:
            filtered_prices = all_prices
        
        # Convert to response format
        commodities_data = []
        for symbol, price_data in filtered_prices.items():
            commodities_data.append({
                "symbol": symbol,
                "name": price_data.name,
                "price": price_data.price,
                "unit": price_data.unit,
                "change_pct": price_data.change_pct,
                "timestamp": int(price_data.timestamp.timestamp() * 1000),
                "source": price_data.source
            })
        
        return {
            "commodities": commodities_data,
            "count": len(commodities_data),
            "timestamp": int(commodities_feed.get_latest_prices()[list(commodities_feed.get_latest_prices().keys())[0]].timestamp.timestamp() * 1000) if commodities_data else 0
        }
        
    except Exception as e:
        logger.error(f"Failed to get commodities: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.options("/all")
async def options_all_markets():
    """Handle OPTIONS preflight for CORS."""
    return {}


@router.get("/all")
async def get_all_markets() -> Dict[str, Any]:
    """
    Get all market data in one call.
    
    Returns stocks, forex, and commodities data.
    Useful for dashboard overview.
    """
    try:
        stocks_feed = get_stocks_feed()
        forex_feed = get_forex_feed()
        commodities_feed = get_commodities_feed()
        
        stocks = []
        for symbol, price_data in stocks_feed.get_latest_prices().items():
            stocks.append({
                "symbol": symbol,
                "price": price_data.price,
                "change_pct": price_data.change_pct,
                "volume": price_data.volume,
                "source": price_data.source
            })
        
        forex = []
        for pair, rate_data in forex_feed.get_latest_rates().items():
            forex.append({
                "pair": pair,
                "rate": rate_data.rate,
                "source": rate_data.source
            })
        
        commodities = []
        for symbol, price_data in commodities_feed.get_latest_prices().items():
            commodities.append({
                "symbol": symbol,
                "name": price_data.name,
                "price": price_data.price,
                "unit": price_data.unit,
                "change_pct": price_data.change_pct,
                "source": price_data.source
            })
        
        return {
            "stocks": stocks,
            "forex": forex,
            "commodities": commodities,
            "counts": {
                "stocks": len(stocks),
                "forex": len(forex),
                "commodities": len(commodities)
            }
        }
        
    except Exception as e:
        logger.error(f"Failed to get all markets: {e}")
        raise HTTPException(status_code=500, detail=str(e))
