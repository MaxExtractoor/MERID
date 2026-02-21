"""
Prediction Markets API
Real prediction market data for MERID (Kalshi)
"""

import aiohttp
import asyncio
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

import logging
logger = logging.getLogger("predictions")

router = APIRouter()

# Global cache
_markets_cache: List[Dict[str, Any]] = []
_last_update: Optional[datetime] = None

class Market(BaseModel):
    id: str
    question: str
    description: str
    category: str
    outcomes: List[str]
    yes_price: float
    no_price: float
    volume: float
    liquidity: float
    end_date: Optional[str] = None

def get_mock_markets():
    """Get mock prediction markets for testing/fallback."""
    return [
        {
            'id': 'bitcoin-price-2024',
            'question': 'Will Bitcoin reach $100,000 by end of 2024?',
            'description': 'Bitcoin price prediction market for end of 2024',
            'category': 'crypto',
            'outcomes': ['Yes', 'No'],
            'yes_price': 0.65,
            'no_price': 0.35,
            'volume': 1500000,
            'liquidity': 500000,
            'end_date': '2024-12-31'
        },
        {
            'id': 'ethereum-upgrade',
            'question': 'Will Ethereum successfully complete the next major upgrade?',
            'description': 'Ethereum network upgrade prediction',
            'category': 'crypto',
            'outcomes': ['Yes', 'No'],
            'yes_price': 0.78,
            'no_price': 0.22,
            'volume': 800000,
            'liquidity': 300000,
            'end_date': '2024-06-30'
        },
        {
            'id': 'us-election-2024',
            'question': 'Who will win the 2024 US Presidential Election?',
            'description': 'US Presidential election prediction market',
            'category': 'politics',
            'outcomes': ['Republican', 'Democrat', 'Other'],
            'yes_price': 0.45,
            'no_price': 0.55,
            'volume': 2500000,
            'liquidity': 1000000,
            'end_date': '2024-11-05'
        }
    ]

# Start with empty cache — populated on first fetch
logger.info("[Predictions] Cache initialized (empty — awaiting first Kalshi fetch)")
async def fetch_kalshi_markets():
    """Fetch prediction markets from Kalshi aggregator."""
    global _markets_cache, _last_update
    
    try:
        # Import Kalshi client to fetch real markets
        from monitoring.prediction_markets import get_prediction_market_aggregator
        aggregator = get_prediction_market_aggregator()
        
        # Get markets from Kalshi aggregator
        kalshi_markets = aggregator.get_all_markets()
        markets = []
        
        if kalshi_markets:
            for market_id, market in kalshi_markets.items():
                # Convert Kalshi format to our API format
                markets.append({
                    'id': market.market_id,
                    'question': market.question,
                    'description': f"Kalshi prediction market for {market.category.value}",
                    'category': market.category.value,
                    'outcomes': ['Yes', 'No'],  # Kalshi typically uses Yes/No outcomes
                    'yes_price': market.yes_price,
                    'no_price': market.no_price,
                    'volume': market.volume_24h,
                    'liquidity': market.liquidity,
                    'end_date': datetime.fromtimestamp(market.resolution_date).isoformat() if market.resolution_date else None
                })
            _markets_cache = markets
            _last_update = datetime.now(timezone.utc)
            logger.info(f"[Predictions] Updated with {len(markets)} Kalshi markets")
        else:
            logger.info("[Predictions] No Kalshi markets available")
                    
    except Exception as e:
        logger.error(f"[Predictions] Error fetching Kalshi markets: {e}")
@router.get("/markets")
async def get_markets():
    """Get all prediction markets."""
    return {
        "markets": _markets_cache,
        "last_update": _last_update.isoformat() if _last_update else None,
        "total": len(_markets_cache)
    }

@router.get("/markets/{market_id}")
async def get_market(market_id: str):
    """Get a specific prediction market."""
    market = next((m for m in _markets_cache if m['id'] == market_id), None)
    if not market:
        raise HTTPException(status_code=404, detail="Market not found")
    return market

@router.get("/categories")
async def get_categories():
    """Get all market categories."""
    categories = list(set(m['category'] for m in _markets_cache))
    return {"categories": sorted(categories)}

@router.get("/markets/category/{category}")
async def get_markets_by_category(category: str):
    """Get markets by category."""
    markets = [m for m in _markets_cache if m['category'] == category]
    return {
        "markets": markets,
        "category": category,
        "total": len(markets)
    }

# Background task to refresh markets
async def refresh_markets():
    """Background task to refresh market data."""
    while True:
        await asyncio.sleep(300)  # Refresh every 5 minutes
        await fetch_kalshi_markets()

# Start background refresh task
async def start_refresh_task():
    """Start the background refresh task."""
    asyncio.create_task(refresh_markets())
