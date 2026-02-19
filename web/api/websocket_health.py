"""
WebSocket Health Check Endpoint

Provides health status for all WebSocket endpoints and their connections.
Useful for monitoring, debugging, and ensuring WebSocket infrastructure is operational.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List
from fastapi import APIRouter

from utils.logger import get_logger

logger = get_logger("web.api.websocket_health")

router = APIRouter(prefix="/api/websocket", tags=["websocket-health"])


@router.get("/health")
async def get_websocket_health() -> Dict[str, Any]:
    """
    Get health status of all WebSocket endpoints.
    
    Returns:
        Health status including:
        - Overall status
        - Individual endpoint statuses
        - Active connection counts
        - Uptime information
    """
    try:
        health_status = {
            "status": "healthy",
            "timestamp": int(time.time() * 1000),
            "endpoints": {}
        }
        
        # Check /ws/trades endpoint
        try:
            from web.api.ws_dedicated_streams import get_trades_manager
            trades_manager = get_trades_manager()
            health_status["endpoints"]["trades"] = {
                "path": "/ws/trades",
                "status": "operational",
                "active_connections": len(trades_manager._subscribers),
                "recent_events": len(trades_manager.get_recent_trades(limit=1))
            }
        except Exception as e:
            logger.error(f"Failed to check /ws/trades health: {e}")
            health_status["endpoints"]["trades"] = {
                "path": "/ws/trades",
                "status": "error",
                "error": str(e)
            }
            health_status["status"] = "degraded"
        
        # Check /ws/prices endpoint
        try:
            from web.api.ws_dedicated_streams import get_prices_manager
            prices_manager = get_prices_manager()
            health_status["endpoints"]["prices"] = {
                "path": "/ws/prices",
                "status": "operational",
                "active_connections": len(prices_manager._subscribers),
                "tracked_symbols": len(prices_manager.get_current_prices())
            }
        except Exception as e:
            logger.error(f"Failed to check /ws/prices health: {e}")
            health_status["endpoints"]["prices"] = {
                "path": "/ws/prices",
                "status": "error",
                "error": str(e)
            }
            health_status["status"] = "degraded"
        
        # Check /ws/portfolio endpoint
        try:
            from web.api.ws_dedicated_streams import get_portfolio_manager
            portfolio_manager = get_portfolio_manager()
            health_status["endpoints"]["portfolio"] = {
                "path": "/ws/portfolio",
                "status": "operational",
                "active_connections": len(portfolio_manager._subscribers),
                "has_data": portfolio_manager.get_current_portfolio() is not None
            }
        except Exception as e:
            logger.error(f"Failed to check /ws/portfolio health: {e}")
            health_status["endpoints"]["portfolio"] = {
                "path": "/ws/portfolio",
                "status": "error",
                "error": str(e)
            }
            health_status["status"] = "degraded"
        
        # Check /ws/paper-trading endpoint
        try:
            from trading.paper_trading import get_paper_engine
            paper_engine = get_paper_engine()
            health_status["endpoints"]["paper_trading"] = {
                "path": "/ws/paper-trading",
                "status": "operational",
                "active_portfolios": len(paper_engine.portfolios),
                "total_trades": sum(p.total_trades for p in paper_engine.portfolios.values())
            }
        except Exception as e:
            logger.error(f"Failed to check /ws/paper-trading health: {e}")
            health_status["endpoints"]["paper_trading"] = {
                "path": "/ws/paper-trading",
                "status": "error",
                "error": str(e)
            }
            health_status["status"] = "degraded"
        
        # Check general /ws endpoint
        try:
            from observability.event_stream import get_event_stream
            event_stream = get_event_stream()
            health_status["endpoints"]["general"] = {
                "path": "/ws",
                "status": "operational",
                "active_subscribers": len(event_stream._subscribers) if hasattr(event_stream, '_subscribers') else 0
            }
        except Exception as e:
            logger.error(f"Failed to check /ws health: {e}")
            health_status["endpoints"]["general"] = {
                "path": "/ws",
                "status": "error",
                "error": str(e)
            }
            health_status["status"] = "degraded"
        
        # Calculate summary statistics
        total_endpoints = len(health_status["endpoints"])
        operational_endpoints = sum(
            1 for ep in health_status["endpoints"].values() 
            if ep.get("status") == "operational"
        )
        
        health_status["summary"] = {
            "total_endpoints": total_endpoints,
            "operational": operational_endpoints,
            "degraded": total_endpoints - operational_endpoints,
            "health_percentage": round((operational_endpoints / total_endpoints * 100), 2) if total_endpoints > 0 else 0
        }
        
        # Set overall status based on health percentage
        if health_status["summary"]["health_percentage"] < 50:
            health_status["status"] = "unhealthy"
        elif health_status["summary"]["health_percentage"] < 100:
            health_status["status"] = "degraded"
        
        return health_status
        
    except Exception as e:
        logger.error(f"WebSocket health check failed: {e}")
        return {
            "status": "error",
            "timestamp": int(time.time() * 1000),
            "error": str(e),
            "endpoints": {}
        }


@router.get("/connections")
async def get_websocket_connections() -> Dict[str, Any]:
    """
    Get detailed information about active WebSocket connections.
    
    Returns:
        Detailed connection information for monitoring and debugging.
    """
    try:
        connections = {
            "timestamp": int(time.time() * 1000),
            "total_connections": 0,
            "by_endpoint": {}
        }
        
        # Get connection details for each endpoint
        try:
            from web.api.ws_dedicated_streams import (
                get_trades_manager,
                get_prices_manager,
                get_portfolio_manager
            )
            
            trades_manager = get_trades_manager()
            prices_manager = get_prices_manager()
            portfolio_manager = get_portfolio_manager()
            
            trades_count = len(trades_manager._subscribers)
            prices_count = len(prices_manager._subscribers)
            portfolio_count = len(portfolio_manager._subscribers)
            
            connections["by_endpoint"]["trades"] = {
                "path": "/ws/trades",
                "connections": trades_count,
                "recent_events_count": len(trades_manager.get_recent_trades(limit=100))
            }
            
            connections["by_endpoint"]["prices"] = {
                "path": "/ws/prices",
                "connections": prices_count,
                "tracked_symbols": list(prices_manager.get_current_prices().keys())
            }
            
            connections["by_endpoint"]["portfolio"] = {
                "path": "/ws/portfolio",
                "connections": portfolio_count,
                "has_current_data": portfolio_manager.get_current_portfolio() is not None
            }
            
            connections["total_connections"] = trades_count + prices_count + portfolio_count
            
        except Exception as e:
            logger.error(f"Failed to get WebSocket connection details: {e}")
            connections["error"] = str(e)
        
        return connections
        
    except Exception as e:
        logger.error(f"Failed to get WebSocket connections: {e}")
        return {
            "timestamp": int(time.time() * 1000),
            "error": str(e),
            "total_connections": 0,
            "by_endpoint": {}
        }


@router.get("/metrics")
async def get_websocket_metrics() -> Dict[str, Any]:
    """
    Get performance metrics for WebSocket endpoints.
    
    Returns:
        Metrics including message counts, latency, and throughput.
    """
    try:
        metrics = {
            "timestamp": int(time.time() * 1000),
            "endpoints": {}
        }
        
        # Get metrics for trades endpoint
        try:
            trades_manager = get_trades_manager()
            
            recent_trades = trades_manager.get_recent_trades(limit=100)
            
            metrics["endpoints"]["trades"] = {
                "path": "/ws/trades",
                "total_events_buffered": len(recent_trades),
                "active_subscribers": len(trades_manager._subscribers),
                "events_per_subscriber": round(
                    len(recent_trades) / len(trades_manager._subscribers), 2
                ) if len(trades_manager._subscribers) > 0 else 0
            }
        except Exception as e:
            logger.error(f"Failed to get trades metrics: {e}")
            metrics["endpoints"]["trades"] = {"error": str(e)}
        
        # Get metrics for prices endpoint
        try:
            prices_manager = get_prices_manager()
            
            current_prices = prices_manager.get_current_prices()
            
            metrics["endpoints"]["prices"] = {
                "path": "/ws/prices",
                "symbols_tracked": len(current_prices),
                "active_subscribers": len(prices_manager._subscribers),
                "total_symbol_subscriptions": sum(
                    len(symbols) for symbols in prices_manager._subscribers.values()
                )
            }
        except Exception as e:
            logger.error(f"Failed to get prices metrics: {e}")
            metrics["endpoints"]["prices"] = {"error": str(e)}
        
        # Get metrics for portfolio endpoint
        try:
            
            portfolio_manager = get_portfolio_manager()
            paper_engine = get_paper_engine()
            
            global_stats = paper_engine.get_global_stats()
            
            metrics["endpoints"]["portfolio"] = {
                "path": "/ws/portfolio",
                "active_subscribers": len(portfolio_manager._subscribers),
                "active_portfolios": global_stats.get("accounts", 0),
                "total_positions": global_stats.get("active_positions", 0),
                "trades_24h": global_stats.get("trades_24h", 0)
            }
        except Exception as e:
            logger.error(f"Failed to get portfolio metrics: {e}")
            metrics["endpoints"]["portfolio"] = {"error": str(e)}
        
        return metrics
        
    except Exception as e:
        logger.error(f"Failed to get WebSocket metrics: {e}")
        return {
            "timestamp": int(time.time() * 1000),
            "error": str(e),
            "endpoints": {}
        }
