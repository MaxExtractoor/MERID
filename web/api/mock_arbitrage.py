"""
Mock API endpoints for arbitrage opportunities
"""

from fastapi import APIRouter
from typing import Dict, List, Any
import random
import time

router = APIRouter()

# Mock data store
mock_opportunities = []

@router.get("/opportunities")
async def get_arbitrage_opportunities():
    """Get current arbitrage opportunities"""
    # Generate mock opportunities if empty
    if not mock_opportunities:
        symbols = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "MATIC/USDT", "AVAX/USDT"]
        venues = ["Binance", "Coinbase", "Kraken", "Gemini", "KuCoin"]
        
        for i, symbol in enumerate(symbols):
            for j in range(random.randint(1, 3)):  # 1-3 opportunities per symbol
                buy_venue = random.choice(venues)
                sell_venue = random.choice([v for v in venues if v != buy_venue])
                buy_price = random.uniform(20000, 60000) if "BTC" in symbol else random.uniform(1000, 5000)
                profit_percent = random.uniform(0.1, 2.5)
                sell_price = buy_price * (1 + profit_percent / 100)
                
                mock_opportunities.append({
                    "id": f"arb_{i}_{j}",
                    "symbol": symbol,
                    "buy_venue": buy_venue,
                    "sell_venue": sell_venue,
                    "buy_price": buy_price,
                    "sell_price": sell_price,
                    "profit_percent": profit_percent,
                    "size": random.uniform(0.1, 10.0),
                    "timestamp": time.time() - random.randint(0, 300)
                })
    
    return {"opportunities": mock_opportunities}

@router.get("/stats")
async def get_arbitrage_stats():
    """Get arbitrage statistics"""
    if not mock_opportunities:
        return {
            "total_opportunities": 0,
            "avg_profit_percent": 0,
            "active_venues": 0,
            "last_update": time.time()
        }
    
    total_opps = len(mock_opportunities)
    avg_profit = sum(opp["profit_percent"] for opp in mock_opportunities) / total_opps
    active_venues = len(set(opp["buy_venue"] for opp in mock_opportunities) | 
                      set(opp["sell_venue"] for opp in mock_opportunities))
    
    return {
        "total_opportunities": total_opps,
        "avg_profit_percent": avg_profit,
        "active_venues": active_venues,
        "last_update": time.time()
    }

@router.post("/execute")
async def execute_arbitrage(opportunity_id: str):
    """Execute an arbitrage opportunity"""
    # Find the opportunity
    opportunity = next((opp for opp in mock_opportunities if opp["id"] == opportunity_id), None)
    if not opportunity:
        return {"error": "Opportunity not found"}
    
    # Mock execution
    return {
        "success": True,
        "opportunity_id": opportunity_id,
        "executed_at": time.time(),
        "estimated_profit": opportunity["profit_percent"],
        "status": "executed"
    }

@router.get("/venues")
async def get_arbitrage_venues():
    """Get supported arbitrage venues"""
    return {
        "venues": [
            {"id": "binance", "name": "Binance", "status": "active"},
            {"id": "coinbase", "name": "Coinbase", "status": "active"},
            {"id": "kraken", "name": "Kraken", "status": "active"},
            {"id": "gemini", "name": "Gemini", "status": "active"},
            {"id": "kucoin", "name": "KuCoin", "status": "active"}
        ]
    }
