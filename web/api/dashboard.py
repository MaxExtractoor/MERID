"""
Dashboard API Endpoints
Provides real-time data for the React dashboard
"""
from fastapi import APIRouter, HTTPException
from typing import Dict, Any, List, Optional
from datetime import datetime
import random

from utils.logger import get_logger

logger = get_logger("api.dashboard")

router = APIRouter(prefix="/api", tags=["Dashboard"])


@router.get("/portfolio/summary")
async def get_portfolio_summary() -> Dict[str, Any]:
    """
    Get portfolio summary for dashboard overview.
    Returns equity, P&L, margin, and active bots count.
    """
    try:
        # TODO: Connect to real portfolio engine
        # For now, return realistic mock data
        return {
            "equity": 1284732.45,
            "dailyPnl": 12847.32,
            "dailyPnlPct": 2.34,
            "availableMargin": 456231.89,
            "activeBots": 12
        }
    except Exception as e:
        logger.error(f"Failed to get portfolio summary: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/prices/live")
async def get_live_prices(symbols: str) -> Dict[str, Any]:
    """
    Get live prices for multiple symbols.
    Query param: symbols (comma-separated, e.g., "BTC-USD,ETH-USD")
    """
    try:
        from data.live_price_feed import get_live_price_feed
        
        symbol_list = [s.strip() for s in symbols.split(",")]
        prices = []
        
        # Try to get real prices from live feed
        try:
            feed = get_live_price_feed()
            for symbol in symbol_list:
                # Try to get real price
                price_data = feed.get_latest_price(symbol)
                if price_data and 'price' in price_data:
                    prices.append({
                        "symbol": symbol,
                        "price": round(price_data['price'], 2),
                        "change": round(price_data.get('change_24h', 0), 2),
                        "volume": price_data.get('volume_24h', 'N/A')
                    })
                else:
                    # Fallback to mock data if real price unavailable
                    raise ValueError(f"No price data for {symbol}")
        except Exception as e:
            logger.warning(f"Failed to get real prices, using fallback: {e}")
            # Fallback mock data
            base_prices = {
                "BTC-USD": 103500.00,  # Updated to realistic 2026 price
                "ETH-USD": 3850.00,
                "SOL-USD": 145.00,
                "AAPL": 178.92,
                "NVDA": 456.78,
                "TSLA": 234.56,
                "MSFT": 389.12
            }
            
            for symbol in symbol_list:
                if symbol in base_prices:
                    base_price = base_prices[symbol]
                    variation = random.uniform(-0.02, 0.03)
                    current_price = base_price * (1 + variation)
                    change_pct = variation * 100
                    
                    if symbol.endswith("-USD"):
                        volume = f"{random.uniform(0.8, 1.5):.1f}B"
                    else:
                        volume = f"{random.randint(400, 600)}M"
                    
                    prices.append({
                        "symbol": symbol,
                        "price": round(current_price, 2),
                        "change": round(change_pct, 2),
                        "volume": volume
                    })
        
        return {"prices": prices}
    except Exception as e:
        logger.error(f"Failed to get live prices: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/orders/recent")
async def get_recent_orders(limit: int = 10) -> Dict[str, Any]:
    """
    Get recent order activity for dashboard.
    """
    try:
        # TODO: Connect to real order management system
        # For now, return realistic mock data
        orders = [
            {
                "time": "10:23:45",
                "action": "BUY BTC",
                "size": "0.5",
                "price": "43256.78",
                "status": "FILLED"
            },
            {
                "time": "10:15:22",
                "action": "SELL ETH",
                "size": "2.3",
                "price": "2234.56",
                "status": "FILLED"
            },
            {
                "time": "09:58:11",
                "action": "BUY SOL",
                "size": "100",
                "price": "98.45",
                "status": "FILLED"
            },
            {
                "time": "09:45:33",
                "action": "BUY AAPL",
                "size": "50",
                "price": "178.92",
                "status": "PARTIAL"
            },
            {
                "time": "09:32:18",
                "action": "SELL NVDA",
                "size": "25",
                "price": "456.78",
                "status": "FILLED"
            }
        ]
        
        return {"orders": orders[:limit]}
    except Exception as e:
        logger.error(f"Failed to get recent orders: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/agents/activity")
async def get_agent_activity() -> Dict[str, Any]:
    """
    Get current agent activity and status.
    """
    try:
        # TODO: Connect to real agent orchestrator
        # For now, return realistic mock data
        agents = [
            {
                "agent_id": "analyst-gemma-01",
                "agent_name": "Analyst Gemma",
                "status": "active",
                "last_action": "Analyzed BTC market trends",
                "last_action_time": "2m ago",
                "tasks_completed": 142,
                "current_task": "Processing ETH signals"
            },
            {
                "agent_id": "risk-01",
                "agent_name": "Risk Monitor",
                "status": "active",
                "last_action": "Updated exposure limits",
                "last_action_time": "5m ago",
                "tasks_completed": 89,
                "current_task": "Monitoring portfolio risk"
            },
            {
                "agent_id": "strategy-agent-01",
                "agent_name": "Strategy Agent",
                "status": "idle",
                "last_action": "Generated trading signals",
                "last_action_time": "15m ago",
                "tasks_completed": 67,
                "current_task": None
            },
            {
                "agent_id": "analyst-llama-01",
                "agent_name": "Analyst Llama",
                "status": "active",
                "last_action": "Sentiment analysis complete",
                "last_action_time": "1m ago",
                "tasks_completed": 156,
                "current_task": "Analyzing news feeds"
            },
            {
                "agent_id": "skeptic-01",
                "agent_name": "Skeptic",
                "status": "active",
                "last_action": "Validated trade signals",
                "last_action_time": "3m ago",
                "tasks_completed": 98,
                "current_task": "Reviewing risk parameters"
            },
            {
                "agent_id": "synthesizer-01",
                "agent_name": "Synthesizer",
                "status": "idle",
                "last_action": "Aggregated agent insights",
                "last_action_time": "8m ago",
                "tasks_completed": 45,
                "current_task": None
            },
            {
                "agent_id": "archivist-01",
                "agent_name": "Archivist",
                "status": "active",
                "last_action": "Logged system events",
                "last_action_time": "30s ago",
                "tasks_completed": 234,
                "current_task": "Archiving trade history"
            },
            {
                "agent_id": "meta-audit-01",
                "agent_name": "Meta Auditor",
                "status": "active",
                "last_action": "Performance audit complete",
                "last_action_time": "10m ago",
                "tasks_completed": 23,
                "current_task": "Monitoring agent health"
            }
        ]
        
        return {
            "agents": agents,
            "summary": {
                "total": len(agents),
                "active": sum(1 for a in agents if a["status"] == "active"),
                "idle": sum(1 for a in agents if a["status"] == "idle"),
                "error": sum(1 for a in agents if a["status"] == "error")
            }
        }
    except Exception as e:
        logger.error(f"Failed to get agent activity: {e}")
        raise HTTPException(status_code=500, detail=str(e))
