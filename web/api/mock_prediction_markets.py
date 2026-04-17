"""
Mock Prediction Markets API - Phase 2.2
Provides mock endpoints for prediction markets functionality
"""

from fastapi import APIRouter, HTTPException
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta, timezone
import random
import json

router = APIRouter()

# Mock data storage
mock_markets = []
mock_stats = {}

def initialize_mock_data():
    """Initialize mock prediction markets data"""
    global mock_markets, mock_stats
    
    mock_markets = [
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
            'end_date': '2024-12-31',
            'created_at': '2024-01-01T00:00:00Z'
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
            'end_date': '2024-06-30',
            'created_at': '2024-01-15T00:00:00Z'
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
            'end_date': '2024-11-05',
            'created_at': '2024-01-01T00:00:00Z'
        },
        {
            'id': 'apple-earnings-q2',
            'question': 'Will Apple beat Q2 2024 earnings expectations?',
            'description': 'Apple Q2 2024 earnings prediction',
            'category': 'stocks',
            'outcomes': ['Yes', 'No'],
            'yes_price': 0.58,
            'no_price': 0.42,
            'volume': 600000,
            'liquidity': 200000,
            'end_date': '2024-05-01',
            'created_at': '2024-02-01T00:00:00Z'
        },
        {
            'id': 'climate-target-2030',
            'question': 'Will global temperatures stay below 1.5°C increase by 2030?',
            'description': 'Climate change temperature target prediction',
            'category': 'environment',
            'outcomes': ['Yes', 'No'],
            'yes_price': 0.32,
            'no_price': 0.68,
            'volume': 400000,
            'liquidity': 150000,
            'end_date': '2030-12-31',
            'created_at': '2024-01-01T00:00:00Z'
        },
        {
            'id': 'super-bowl-2025',
            'question': 'Which team will win Super Bowl 2025?',
            'description': 'Super Bowl 2025 champion prediction',
            'category': 'sports',
            'outcomes': ['Chiefs', '49ers', 'Bills', 'Other'],
            'yes_price': 0.25,
            'no_price': 0.75,
            'volume': 1200000,
            'liquidity': 800000,
            'end_date': '2025-02-09',
            'created_at': '2024-02-15T00:00:00Z'
        }
    ]
    
    # Calculate stats
    total_volume = sum(market['volume'] for market in mock_markets)
    active_markets = len([m for m in mock_markets if datetime.fromisoformat(m['end_date'].replace('Z', '+00:00')) > datetime.now(timezone.utc)])
    categories = len(set(market['category'] for market in mock_markets))
    
    mock_stats = {
        'total_markets': len(mock_markets),
        'active_markets': active_markets,
        'total_volume': total_volume,
        'categories': categories,
        'last_updated': datetime.now(timezone.utc).isoformat()
    }

# Initialize data on module load
initialize_mock_data()

@router.get("/markets")
async def get_markets():
    """Get all prediction markets"""
    return {
        "markets": mock_markets,
        "last_update": mock_stats.get('last_updated'),
        "total": len(mock_markets)
    }

@router.get("/markets/{market_id}")
async def get_market(market_id: str):
    """Get a specific prediction market"""
    market = next((m for m in mock_markets if m['id'] == market_id), None)
    if not market:
        raise HTTPException(status_code=404, detail="Market not found")
    return market

@router.get("/categories")
async def get_categories():
    """Get all market categories"""
    categories = list(set(m['category'] for m in mock_markets))
    return {"categories": sorted(categories)}

@router.get("/markets/category/{category}")
async def get_markets_by_category(category: str):
    """Get markets by category"""
    markets = [m for m in mock_markets if m['category'] == category]
    return {
        "markets": markets,
        "category": category,
        "total": len(markets)
    }

@router.get("/stats")
async def get_stats():
    """Get prediction markets statistics"""
    return mock_stats

@router.post("/markets/{market_id}/update")
async def update_market(market_id: str, update_data: Dict[str, Any]):
    """Update market prices (mock trading simulation)"""
    market = next((m for m in mock_markets if m['id'] == market_id), None)
    if not market:
        raise HTTPException(status_code=404, detail="Market not found")
    
    # Update prices with some randomness
    if 'yes_price' in update_data:
        market['yes_price'] = max(0.01, min(0.99, update_data['yes_price']))
        market['no_price'] = 1 - market['yes_price']
    
    if 'volume' in update_data:
        market['volume'] += update_data['volume']
    
    # Update stats
    mock_stats['total_volume'] = sum(m['volume'] for m in mock_markets)
    mock_stats['last_updated'] = datetime.now(timezone.utc).isoformat()
    
    return market

@router.get("/trending")
async def get_trending_markets():
    """Get trending markets (by volume)"""
    trending = sorted(mock_markets, key=lambda x: x['volume'], reverse=True)[:5]
    return {
        "trending": trending,
        "total": len(trending)
    }

@router.get("/search")
async def search_markets(q: str = "", category: Optional[str] = None):
    """Search markets by query and optional category"""
    results = mock_markets
    
    # Filter by category if specified
    if category:
        results = [m for m in results if m['category'] == category]
    
    # Filter by search query
    if q:
        q_lower = q.lower()
        results = [m for m in results if 
                  q_lower in m['question'].lower() or 
                  q_lower in m['description'].lower()]
    
    return {
        "markets": results,
        "query": q,
        "category": category,
        "total": len(results)
    }

# WebSocket event simulation
def generate_market_update():
    """Generate random market update for WebSocket"""
    if not mock_markets:
        return None
    
    market = random.choice(mock_markets)
    
    # Random price movement
    price_change = random.uniform(-0.05, 0.05)
    new_yes_price = max(0.01, min(0.99, market['yes_price'] + price_change))
    new_no_price = 1 - new_yes_price
    
    return {
        "type": "market_updated",
        "payload": {
            "id": market['id'],
            "yes_price": new_yes_price,
            "no_price": new_no_price,
            "volume": market['volume'] + random.randint(1000, 10000),
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
    }

def generate_stats_update():
    """Generate stats update for WebSocket"""
    return {
        "type": "stats_updated",
        "payload": {
            **mock_stats,
            "last_updated": datetime.now(timezone.utc).isoformat()
        }
    }
