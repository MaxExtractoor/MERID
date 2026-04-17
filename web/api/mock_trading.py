"""
Mock API endpoints for trading portfolio
"""

from fastapi import APIRouter
from typing import Dict, List, Any
import time
import random

router = APIRouter()

@router.get("/")
async def get_portfolio():
    """Get trading portfolio summary"""
    return {
        "total_pnl": random.uniform(-1000, 5000),
        "day_pnl": random.uniform(-500, 1000),
        "available_margin": random.uniform(10000, 50000),
        "open_positions": random.randint(0, 10),
        "leverage": random.uniform(1.0, 5.0),
        "total_equity": random.uniform(20000, 100000)
    }

@router.get("/positions")
async def get_positions():
    """Get open positions"""
    positions = []
    for i in range(random.randint(0, 5)):
        positions.append({
            "id": f"position_{i}",
            "market": f"BTC/USDT",
            "side": random.choice(["long", "short"]),
            "size": random.uniform(0.1, 10.0),
            "entry_price": random.uniform(20000, 60000),
            "mark_price": random.uniform(20000, 60000),
            "pnl": random.uniform(-1000, 1000)
        })
    
    return {"positions": positions}

@router.get("/trades")
async def get_trades(limit: int = 20):
    """Get recent trades"""
    trades = []
    for i in range(limit):
        trades.append({
            "id": f"trade_{i}",
            "symbol": random.choice(["BTC/USDT", "ETH/USDT", "SOL/USDT"]),
            "side": random.choice(["buy", "sell"]),
            "price": random.uniform(20000, 60000),
            "size": random.uniform(0.1, 10.0),
            "timestamp": time.time() - random.randint(0, 3600),
            "venue": random.choice(["Binance", "Coinbase", "Kraken"])
        })
    
    return {"trades": trades}

@router.get("/alerts")
async def get_alerts(limit: int = 10):
    """Get trading alerts"""
    alerts = []
    for i in range(limit):
        alerts.append({
            "id": f"alert_{i}",
            "title": random.choice(["Margin Warning", "Position Limit", "Price Alert"]),
            "message": f"Alert message {i+1}",
            "type": random.choice(["warning", "info", "success", "error"]),
            "timestamp": time.time() - random.randint(0, 3600)
        })
    
    return {"alerts": alerts}

@router.get("/activity")
async def get_activity(limit: int = 15):
    """Get market activity"""
    activity = []
    for i in range(limit):
        activity.append({
            "id": f"activity_{i}",
            "title": random.choice(["Market Update", "Volume Spike", "Price Movement"]),
            "description": f"Activity description {i+1}",
            "timestamp": time.time() - random.randint(0, 3600)
        })
    
    return {"activity": activity}
