"""
Predictions API - Enhanced Polymarket integration with filtering and analytics
Bloomberg Terminal-grade prediction markets interface
"""

from __future__ import annotations

import asyncio
from typing import Dict, List, Optional
from datetime import datetime, timedelta
from fastapi import APIRouter, HTTPException, Query
import aiohttp

router = APIRouter(prefix="/api/v1/predictions", tags=["predictions"])

# Global cache
_markets_cache: List[dict] = []
_last_update = datetime.now()


async def fetch_polymarket_markets():
    """Fetch prediction markets from Polymarket Gamma API."""
    global _markets_cache, _last_update
    
    try:
        async with aiohttp.ClientSession() as session:
            # Fetch trending markets
            url = "https://gamma-api.polymarket.com/markets?limit=100&active=true"
            async with session.get(url) as response:
                if response.status == 200:
                    data = await response.json()
                    
                    markets = []
                    for market in data:
                        # Parse market data
                        outcomes = market.get('outcomes', ['Yes', 'No'])
                        prices = market.get('outcomePrices', ['0.5', '0.5'])
                        
                        # Calculate metrics
                        yes_price = float(prices[0]) if len(prices) > 0 else 0.5
                        no_price = float(prices[1]) if len(prices) > 1 else 0.5
                        
                        volume = float(market.get('volume', 0))
                        liquidity = float(market.get('liquidity', 0))
                        
                        # Categorize market
                        question = market.get('question', '').lower()
                        category = categorize_market(question)
                        
                        markets.append({
                            'id': market.get('id', ''),
                            'question': market.get('question', 'Unknown'),
                            'description': market.get('description', '')[:200],
                            'category': category,
                            'outcomes': outcomes,
                            'yes_price': yes_price,
                            'no_price': no_price,
                            'yes_percentage': yes_price * 100,
                            'no_percentage': no_price * 100,
                            'volume': volume,
                            'volume_24h': float(market.get('volume24hr', 0)),
                            'liquidity': liquidity,
                            'end_date': market.get('endDate', ''),
                            'closed': market.get('closed', False),
                            'active': market.get('active', True),
                            'created_at': market.get('createdAt', ''),
                            'tags': market.get('tags', []),
                            'image': market.get('image', ''),
                            'url': f"https://polymarket.com/event/{market.get('slug', '')}",
                            'timestamp': datetime.now().isoformat()
                        })
                    
                    _markets_cache = markets
                    _last_update = datetime.now()
                    print(f"[Predictions] Loaded {len(markets)} markets from Polymarket")
                    
    except Exception as e:
        print(f"[Predictions] Error fetching Polymarket markets: {e}")


def categorize_market(question: str) -> str:
    """Categorize prediction market based on question."""
    question_lower = question.lower()
    
    categories = {
        'crypto': ['bitcoin', 'btc', 'ethereum', 'eth', 'crypto', 'blockchain', 'defi', 'nft'],
        'politics': ['election', 'president', 'senate', 'congress', 'political', 'vote', 'trump', 'biden'],
        'sports': ['nfl', 'nba', 'mlb', 'nhl', 'soccer', 'football', 'basketball', 'championship', 'super bowl'],
        'finance': ['stock', 'market', 'fed', 'interest rate', 'inflation', 'gdp', 'economy'],
        'technology': ['ai', 'artificial intelligence', 'tech', 'apple', 'google', 'microsoft', 'tesla'],
        'entertainment': ['movie', 'oscar', 'grammy', 'emmy', 'award', 'celebrity'],
        'science': ['climate', 'space', 'nasa', 'research', 'discovery', 'vaccine'],
        'world': ['war', 'peace', 'treaty', 'international', 'country', 'nation']
    }
    
    for category, keywords in categories.items():
        if any(keyword in question_lower for keyword in keywords):
            return category
    
    return 'other'


@router.get("/markets")
async def get_markets(
    category: Optional[str] = Query(None, description="Filter by category: crypto, politics, sports, finance, technology, entertainment, science, world, other"),
    min_volume: Optional[float] = Query(None, description="Minimum 24h volume"),
    min_liquidity: Optional[float] = Query(None, description="Minimum liquidity"),
    sort_by: Optional[str] = Query("volume", description="Sort by: volume, liquidity, yes_price, volume_24h"),
    limit: Optional[int] = Query(50, description="Limit number of results"),
    active_only: Optional[bool] = Query(True, description="Show only active markets")
):
    """Get prediction markets with filtering and sorting."""
    # Update if cache is stale (older than 2 minutes)
    if not _markets_cache or (datetime.now() - _last_update).total_seconds() > 120:
        await fetch_polymarket_markets()
    
    markets = list(_markets_cache)
    
    # Apply filters
    if active_only:
        markets = [m for m in markets if m.get('active', True) and not m.get('closed', False)]
    
    if category:
        markets = [m for m in markets if m.get('category') == category]
    
    if min_volume:
        markets = [m for m in markets if m.get('volume_24h', 0) >= min_volume]
    
    if min_liquidity:
        markets = [m for m in markets if m.get('liquidity', 0) >= min_liquidity]
    
    # Sort markets
    if sort_by == 'volume':
        markets.sort(key=lambda x: x.get('volume', 0), reverse=True)
    elif sort_by == 'liquidity':
        markets.sort(key=lambda x: x.get('liquidity', 0), reverse=True)
    elif sort_by == 'yes_price':
        markets.sort(key=lambda x: x.get('yes_price', 0), reverse=True)
    elif sort_by == 'volume_24h':
        markets.sort(key=lambda x: x.get('volume_24h', 0), reverse=True)
    
    # Apply limit
    markets = markets[:limit]
    
    return {
        'status': 'success',
        'markets': markets,
        'count': len(markets),
        'total_cached': len(_markets_cache),
        'last_update': _last_update.isoformat(),
        'filters': {
            'category': category,
            'min_volume': min_volume,
            'min_liquidity': min_liquidity,
            'sort_by': sort_by,
            'limit': limit,
            'active_only': active_only
        }
    }


@router.get("/markets/{market_id}")
async def get_market_details(market_id: str):
    """Get detailed information for a specific market."""
    if not _markets_cache:
        await fetch_polymarket_markets()
    
    market = next((m for m in _markets_cache if m['id'] == market_id), None)
    
    if not market:
        raise HTTPException(status_code=404, detail="Market not found")
    
    return {
        'status': 'success',
        'market': market
    }


@router.get("/categories")
async def get_categories():
    """Get available categories with market counts."""
    if not _markets_cache:
        await fetch_polymarket_markets()
    
    categories = {}
    for market in _markets_cache:
        cat = market.get('category', 'other')
        categories[cat] = categories.get(cat, 0) + 1
    
    return {
        'status': 'success',
        'categories': categories,
        'total_markets': len(_markets_cache)
    }


@router.get("/trending")
async def get_trending_markets():
    """Get trending markets by volume."""
    if not _markets_cache:
        await fetch_polymarket_markets()
    
    # Sort by 24h volume
    trending = sorted(_markets_cache, key=lambda x: x.get('volume_24h', 0), reverse=True)[:10]
    
    return {
        'status': 'success',
        'trending': trending,
        'count': len(trending)
    }


@router.get("/high-conviction")
async def get_high_conviction_markets():
    """Get markets with strong price signals (>70% or <30%)."""
    if not _markets_cache:
        await fetch_polymarket_markets()
    
    high_conviction = [
        m for m in _markets_cache 
        if m.get('yes_price', 0.5) > 0.7 or m.get('yes_price', 0.5) < 0.3
    ]
    
    # Sort by distance from 50%
    high_conviction.sort(key=lambda x: abs(x.get('yes_price', 0.5) - 0.5), reverse=True)
    
    return {
        'status': 'success',
        'markets': high_conviction[:20],
        'count': len(high_conviction)
    }


@router.get("/close-odds")
async def get_close_odds_markets():
    """Get markets with close odds (45-55%)."""
    if not _markets_cache:
        await fetch_polymarket_markets()
    
    close_odds = [
        m for m in _markets_cache 
        if 0.45 <= m.get('yes_price', 0.5) <= 0.55
    ]
    
    # Sort by volume
    close_odds.sort(key=lambda x: x.get('volume', 0), reverse=True)
    
    return {
        'status': 'success',
        'markets': close_odds[:20],
        'count': len(close_odds)
    }


@router.get("/analytics")
async def get_market_analytics():
    """Get aggregate analytics across all markets."""
    if not _markets_cache:
        await fetch_polymarket_markets()
    
    total_volume = sum(m.get('volume', 0) for m in _markets_cache)
    total_volume_24h = sum(m.get('volume_24h', 0) for m in _markets_cache)
    total_liquidity = sum(m.get('liquidity', 0) for m in _markets_cache)
    
    avg_yes_price = sum(m.get('yes_price', 0) for m in _markets_cache) / len(_markets_cache) if _markets_cache else 0
    
    # Category breakdown
    category_stats = {}
    for market in _markets_cache:
        cat = market.get('category', 'other')
        if cat not in category_stats:
            category_stats[cat] = {
                'count': 0,
                'volume': 0,
                'avg_yes_price': 0
            }
        category_stats[cat]['count'] += 1
        category_stats[cat]['volume'] += market.get('volume', 0)
    
    # Calculate averages
    for cat in category_stats:
        cat_markets = [m for m in _markets_cache if m.get('category') == cat]
        if cat_markets:
            category_stats[cat]['avg_yes_price'] = sum(m.get('yes_price', 0) for m in cat_markets) / len(cat_markets)
    
    return {
        'status': 'success',
        'analytics': {
            'total_markets': len(_markets_cache),
            'total_volume': total_volume,
            'total_volume_24h': total_volume_24h,
            'total_liquidity': total_liquidity,
            'average_yes_price': avg_yes_price,
            'category_breakdown': category_stats
        }
    }


@router.post("/refresh")
async def refresh_markets():
    """Force refresh markets from Polymarket."""
    await fetch_polymarket_markets()
    
    return {
        'status': 'success',
        'message': 'Markets refreshed',
        'count': len(_markets_cache),
        'timestamp': datetime.now().isoformat()
    }
