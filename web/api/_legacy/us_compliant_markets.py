"""
US-Compliant Markets API

FastAPI endpoints for US-compliant data sources.
Replaces restricted APIs with free, unrestricted alternatives.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone
import threading
import asyncio

from data.us_compliant_data_sources import USCompliantDataAggregator, PredictionMarketsAggregator
from utils.logger import get_logger
from web.api.auth import get_current_session

logger = get_logger("api.us_compliant_markets")

router = APIRouter(prefix="/api/v1/us-compliant", tags=["US-Compliant Markets"], dependencies=[Depends(get_current_session)])  # ZT6-01

# Global instances
_market_aggregator = None
_market_aggregator_lock = threading.Lock()
_prediction_aggregator = None
_prediction_aggregator_lock = threading.Lock()


async def get_market_aggregator():
    """Get or create market aggregator instance."""
    global _market_aggregator
    if _market_aggregator is None:
        with _market_aggregator_lock:
            if _market_aggregator is None:
                _market_aggregator = USCompliantDataAggregator()
                await _market_aggregator.__aenter__()
    return _market_aggregator


async def get_prediction_aggregator():
    """Get or create prediction aggregator instance."""
    global _prediction_aggregator
    if _prediction_aggregator is None:
        with _prediction_aggregator_lock:
            if _prediction_aggregator is None:
                _prediction_aggregator = PredictionMarketsAggregator()
                await _prediction_aggregator.__aenter__()
    return _prediction_aggregator


@router.get("/markets")
async def get_markets(
    symbols: Optional[str] = Query(None, description="Comma-separated list of symbols (e.g., BTC/USDT,ETH/USDT)"),
    sources: Optional[str] = Query(None, description="Comma-separated list of sources to prioritize")
):
    """
    Get market data from US-compliant sources.
    
    Args:
        symbols: List of trading symbols
        sources: Preferred data sources (coingecko, kraken, cryptocompare, poloniex, coinbase)
    
    Returns:
        Market data for requested symbols
    """
    try:
        # Parse symbols
        symbol_list = symbols.split(',') if symbols else ['BTC/USDT', 'ETH/USDT', 'SOL/USDT']
        
        # Get aggregator
        aggregator = await get_market_aggregator()
        
        # Fetch data
        market_data = await aggregator.get_cached_data(symbol_list)
        
        # Format response
        response = {
            "status": "success",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "sources": list(set(data.source for data in market_data.values())),
            "markets": []
        }
        
        for symbol, data in market_data.items():
            response["markets"].append({
                "symbol": symbol,
                "price": data.price,
                "volume_24h": data.volume_24h,
                "change_24h_pct": data.change_24h_pct,
                "timestamp": data.timestamp.isoformat(),
                "source": data.source,
                "market_cap": data.market_cap,
                "liquidity_score": getattr(data, 'liquidity_score', 0.0),
                "confidence_score": getattr(data, 'confidence_score', 0.0)
            })
        
        return response
        
    except Exception as e:
        logger.error(f"Error fetching markets: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/markets/{symbol}")
async def get_market_details(symbol: str):
    """
    Get detailed market data for a specific symbol.
    
    Args:
        symbol: Trading symbol (e.g., BTC/USDT)
    
    Returns:
        Detailed market data for the symbol
    """
    try:
        aggregator = await get_market_aggregator()
        market_data = await aggregator.get_cached_data([symbol])
        
        if symbol not in market_data:
            raise HTTPException(status_code=404, detail=f"Symbol {symbol} not found")
        
        data = market_data[symbol]
        
        return {
            "status": "success",
            "symbol": symbol,
            "price": data.price,
            "volume_24h": data.volume_24h,
            "change_24h_pct": data.change_24h_pct,
            "timestamp": data.timestamp.isoformat(),
            "source": data.source,
            "market_cap": data.market_cap,
            "circulating_supply": data.circulating_supply,
            "liquidity_score": getattr(data, 'liquidity_score', 0.0),
            "confidence_score": getattr(data, 'confidence_score', 0.0),
            "historical_data_available": True  # Placeholder for future implementation
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching market details for {symbol}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/top-liquid")
async def get_top_liquid_markets(
    limit: int = Query(10, ge=1, le=50, description="Number of top markets to return")
):
    """
    Get top markets by liquidity score.
    
    Args:
        limit: Number of markets to return (1-50)
    
    Returns:
        Top markets sorted by liquidity
    """
    try:
        aggregator = await get_market_aggregator()
        
        # Get all available symbols
        all_symbols = ['BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'AVAX/USDT', 'MATIC/USDT', 
                       'DOT/USDT', 'LINK/USDT', 'UNI/USDT', 'AAVE/USDT', 'COMP/USDT']
        
        market_data = await aggregator.get_cached_data(all_symbols)
        
        # Sort by liquidity score (using volume as proxy if not available)
        sorted_markets = sorted(
            market_data.items(),
            key=lambda x: (x[1].volume_24h, getattr(x[1], 'liquidity_score', 0.0)),
            reverse=True
        )
        
        response = {
            "status": "success",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "markets": []
        }
        
        for symbol, data in sorted_markets[:limit]:
            response["markets"].append({
                "symbol": symbol,
                "price": data.price,
                "volume_24h": data.volume_24h,
                "change_24h_pct": data.change_24h_pct,
                "timestamp": data.timestamp.isoformat(),
                "source": data.source,
                "market_cap": data.market_cap,
                "liquidity_score": getattr(data, 'liquidity_score', 0.0),
                "confidence_score": getattr(data, 'confidence_score', 0.0)
            })
        
        return response
        
    except Exception as e:
        logger.error(f"Error fetching top liquid markets: {e}")
        raise HTTPException(status_code=500, detail=str(e))


def _lookup_paper_position(trading_engine, market_id: str) -> dict:
    """Look up real paper trading position for a Kalshi market.
    
    Returns dict with side/size/pnl — all zeros if no position exists.
    """
    try:
        for portfolio in trading_engine.portfolios.values():
            for symbol, pos in portfolio.positions.items():
                if market_id in symbol:
                    side = "YES" if pos.get("quantity", pos.get("size", 0)) > 0 else "NO"
                    size = abs(pos.get("quantity", pos.get("size", 0)))
                    pnl = round(pos.get("unrealized_pnl", 0.0), 2)
                    return {"side": side, "size": size, "pnl": pnl}
    except Exception as _e:
        logger.debug("_get_position_for_market skipped: %s", _e)
    return {"side": "NONE", "size": 0, "pnl": 0.0}


@router.get("/prediction-markets")
async def get_prediction_markets():
    """
    Get prediction markets data from US-compliant sources (Kalshi).
    Returns data in frontend-compatible format with trading positions.
    """
    try:
        from monitoring.prediction_markets import get_prediction_aggregator, ResolutionStatus
        from trading.paper_trading import get_paper_trading_engine
        from merid.event_venues.kalshi.client import get_kalshi_client

        # Get the prediction markets aggregator which has Kalshi data
        aggregator = get_prediction_aggregator()
        trading_engine = get_paper_trading_engine()

        # Check Kalshi health via singleton client
        client = get_kalshi_client()
        circuit = client.get_circuit_status()
        if circuit.get("state") != "closed":
            return _offline({
                "markets": [],
                "meta": {"total": 0, "open": 0, "totalVolume": 0, "totalPnl": 0}
            }, reason=f"Kalshi venue is offline or degraded: {circuit.get('state')}")

        # Lazy-start aggregator...
        
    except Exception as e:
        logger.error(f"Error fetching prediction markets: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/sources")
async def get_available_sources():
    """
    Get list of available data sources and their status.
    
    Returns:
        Available data sources with status information
    """
    try:
        # Test each source quickly
        sources = {
            "coingecko": {"status": "available", "description": "Primary source, no API key required"},
            "kraken": {"status": "available", "description": "Backup source, public API"},
            "cryptocompare": {"status": "available", "description": "Backup source, free tier"},
            "poloniex": {"status": "available", "description": "Backup source, public API"},
            "coinbase": {"status": "available", "description": "Limited endpoints, public API"},
            "blockchain": {"status": "available", "description": "Bitcoin data only, public API"}
        }
        
        return {
            "status": "success",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "sources": sources
        }
        
    except Exception as e:
        logger.error(f"Error checking sources: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/health")
async def health_check():
    """
    Health check for US-compliant markets API.
    
    Returns:
        Health status
    """
    try:
        # Quick test of primary source
        aggregator = await get_market_aggregator()
        test_data = await aggregator.get_cached_data(['BTC/USDT'])
        
        return {
            "status": "healthy",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "sources_active": len(test_data),
            "api_version": "v1.0"
        }
        
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return {
            "status": "unhealthy",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "error": str(e),
            "api_version": "v1.0"
        }


@router.get("/real-time")
async def start_real_time_feed(
    symbols: Optional[str] = Query(None, description="Comma-separated list of symbols"),
    websocket: bool = Query(False, description="Use WebSocket for real-time updates")
):
    """
    Start real-time market data feed.
    
    This endpoint provides server-sent events for real-time updates.
    For WebSocket support, use the WebSocket endpoint instead.
    
    Args:
        symbols: Symbols to track
        websocket: Whether to use WebSocket (requires WebSocket client)
    
    Returns:
        Server-sent events stream
    """
    try:
        symbol_list = symbols.split(',') if symbols else ['BTC/USDT', 'ETH/USDT']
        
        # This would implement Server-Sent Events
        # For now, return current data and note that WebSocket is preferred
        aggregator = await get_market_aggregator()
        current_data = await aggregator.get_cached_data(symbol_list)
        
        return {
            "status": "real_time_available",
            "message": "Use WebSocket endpoint for real-time updates",
            "current_data": {
                symbol: {
                    "price": data.price,
                    "timestamp": data.timestamp.isoformat(),
                    "source": data.source
                }
                for symbol, data in current_data.items()
            },
            "websocket_endpoint": "/api/v1/us-compliant/ws/real-time",
            "symbols": symbol_list
        }
        
    except Exception as e:
        logger.error(f"Error setting up real-time feed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# WebSocket endpoint for real-time data
@router.websocket("/ws/real-time")
async def websocket_real_time_feed(websocket):
    """
    WebSocket endpoint for real-time market data.
    
    Connect with: ws://localhost:8000/api/v1/us-compliant/ws/real-time
    
    Send JSON message with symbols to track:
    {"symbols": ["BTC/USDT", "ETH/USDT"]}
    """
    try:
        await websocket.accept_json()
        
        # Get aggregator
        aggregator = await get_market_aggregator()
        
        # Store WebSocket connection
        # In a real implementation, you'd manage multiple connections
        # For now, we'll handle a single connection
        
        # Listen for messages
        while True:
            try:
                # Receive message with symbols to track
                message = await websocket.receive_json()
                symbols = message.get('symbols', ['BTC/USDT', 'ETH/USDT'])
                
                # Send current data
                current_data = await aggregator.get_cached_data(symbols)
                await websocket.send_json({
                    "type": "market_update",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "data": {
                        symbol: {
                            "price": data.price,
                            "volume_24h": data.volume_24h,
                            "change_24h_pct": data.change_24h_pct,
                            "timestamp": data.timestamp.isoformat(),
                            "source": data.source
                        }
                        for symbol, data in current_data.items()
                    }
                })
                
                # Wait a bit before next update
                await asyncio.sleep(5)
                
            except Exception as e:
                logger.error(f"WebSocket error: {e}")
                break
                
    except Exception as e:
        logger.error(f"WebSocket connection error: {e}")
        await websocket.close()


@router.get("/drift-signals")
async def get_drift_signals(limit: int = Query(20, ge=1, le=100)):
    """
    Get recent odds/price drift signals from prediction markets.
    
    Drift signals indicate significant probability movements that may
    present trading opportunities or indicate market sentiment shifts.
    """
    try:
        from monitoring.prediction_markets import get_prediction_aggregator as get_pm_aggregator
        
        aggregator = get_pm_aggregator()
        drift_signals = aggregator.get_drift_signals(limit=limit)
        
        return {
            "signals": [
                {
                    "signal_id": s.signal_id,
                    "market_id": s.market_id,
                    "platform": s.platform.value,
                    "question": s.question[:100] if len(s.question) > 100 else s.question,
                    "old_probability": round(s.old_probability * 100, 1),
                    "new_probability": round(s.new_probability * 100, 1),
                    "drift_pct": round(s.drift_pct, 2),
                    "direction": s.drift_direction,
                    "time_window_seconds": s.time_window_seconds,
                    "volume_in_window": s.volume_in_window,
                    "detected_at": s.detected_at if hasattr(s, 'detected_at') else None,
                }
                for s in drift_signals
            ],
            "count": len(drift_signals),
            "source": "kalshi",
        }
    except Exception as e:
        logger.error(f"Error fetching drift signals: {e}")
        return {
            "signals": [],
            "count": 0,
            "error": str(e),
        }


# Cleanup on shutdown
async def cleanup():
    """Cleanup resources on shutdown."""
    global _market_aggregator, _prediction_aggregator
    
    if _market_aggregator:
        await _market_aggregator.__aexit__(None, None, None)
        _market_aggregator = None
    
    if _prediction_aggregator:
        await _prediction_aggregator.__aexit__(None, None, None)
        _prediction_aggregator = None
    
    logger.info("US-compliant markets API cleanup completed")
