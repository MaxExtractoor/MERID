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
            'yes_percentage': 65.0,
            'no_percentage': 35.0,
            'volume': 1500000,
            'volume_24h': 250000,
            'liquidity': 500000,
            'end_date': '2024-12-31',
            'closed': False,
            'active': True,
            'created_at': '2024-01-01',
            'tags': ['crypto', 'bitcoin'],
            'image': 'https://example.com/btc.jpg',
            'url': 'https://polymarket.com/event/bitcoin-price-2024',
            'timestamp': datetime.now().isoformat()
        },
        {
            'id': 'election-2024',
            'question': 'Will the 2024 US Presidential Election go to a recount?',
            'description': 'US Presidential Election recount probability',
            'category': 'politics',
            'outcomes': ['Yes', 'No'],
            'yes_price': 0.25,
            'no_price': 0.75,
            'yes_percentage': 25.0,
            'no_percentage': 75.0,
            'volume': 2000000,
            'volume_24h': 300000,
            'liquidity': 750000,
            'end_date': '2024-11-05',
            'closed': False,
            'active': True,
            'created_at': '2024-01-15',
            'tags': ['politics', 'election'],
            'image': 'https://example.com/election.jpg',
            'url': 'https://polymarket.com/event/election-2024',
            'timestamp': datetime.now().isoformat()
        },
        {
            'id': 'super-bowl-2024',
            'question': 'Will the Kansas City Chiefs win Super Bowl 2024?',
            'description': 'NFL Super Bowl 2024 winner prediction',
            'category': 'sports',
            'outcomes': ['Yes', 'No'],
            'yes_price': 0.55,
            'no_price': 0.45,
            'yes_percentage': 55.0,
            'no_percentage': 45.0,
            'volume': 800000,
            'volume_24h': 120000,
            'liquidity': 300000,
            'end_date': '2024-02-11',
            'closed': False,
            'active': True,
            'created_at': '2024-01-20',
            'tags': ['sports', 'nfl', 'super-bowl'],
            'image': 'https://example.com/sb.jpg',
            'url': 'https://polymarket.com/event/super-bowl-2024',
            'timestamp': datetime.now().isoformat()
        },
        {
            'id': 'fed-rate-cut',
            'question': 'Will the Federal Reserve cut interest rates in Q2 2024?',
            'description': 'Federal Reserve interest rate decision for Q2 2024',
            'category': 'finance',
            'outcomes': ['Yes', 'No'],
            'yes_price': 0.40,
            'no_price': 0.60,
            'yes_percentage': 40.0,
            'no_percentage': 60.0,
            'volume': 1200000,
            'volume_24h': 180000,
            'liquidity': 450000,
            'end_date': '2024-06-30',
            'closed': False,
            'active': True,
            'created_at': '2024-02-01',
            'tags': ['finance', 'fed', 'interest-rates'],
            'image': 'https://example.com/fed.jpg',
            'url': 'https://polymarket.com/event/fed-rate-cut',
            'timestamp': datetime.now().isoformat()
        },
        {
            'id': 'ai-agi-2025',
            'question': 'Will AGI be achieved by 2025?',
            'description': 'Artificial General Intelligence timeline prediction',
            'category': 'technology',
            'outcomes': ['Yes', 'No'],
            'yes_price': 0.15,
            'no_price': 0.85,
            'yes_percentage': 15.0,
            'no_percentage': 85.0,
            'volume': 600000,
            'volume_24h': 90000,
            'liquidity': 200000,
            'end_date': '2025-12-31',
            'closed': False,
            'active': True,
            'created_at': '2024-02-10',
            'tags': ['technology', 'ai', 'agi'],
            'image': 'https://example.com/ai.jpg',
            'url': 'https://polymarket.com/event/ai-agi-2025',
            'timestamp': datetime.now().isoformat()
        }
    ]


# Initialize with mock data immediately
_markets_cache = get_mock_markets()
_last_update = datetime.now()
print(f"[Predictions] Initialized with {len(_markets_cache)} mock markets")


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
=======
=======
>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\web\api\predictions.py
=======
>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\web\api\predictions.py
=======
>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\web\api\predictions.py
=======
>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\web\api\predictions.py
        # Add mock data fallback
        markets = get_mock_markets()
        _markets_cache = markets
        _last_update = datetime.now()
        print(f"[Predictions] Using {len(markets)} mock markets")
=======
=======
>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\web\api\predictions.py


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
=======
=======
>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\web\api\predictions.py
=======
>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\web\api\predictions.py


def categorize_market(question: str) -> str:
    """Categorize prediction market based on question."""
    question_lower = question.lower()
    
    categories = {
        'crypto': ['bitcoin', 'btc', 'ethereum', 'eth', 'crypto', 'blockchain', 'defi', 'nft'],
        'politics': ['election', 'president', 'senate', 'congress', 'political', 'vote', 'trump', 'biden'],
        'sports': ['nfl', 'nba', 'mlb', 'nhl', 'soccer', 'football', 'basketball', 'championship', 'super bowl'],
        'finance': ['stock', 'market', 'fed', 'interest rate', 'inflation', 'gdp', 'economy'],
        'technology': ['ai', 'artificial intelligence', 'tech', 'apple', 'google', 'microsoft', 'tesla'],
        'entertainment': ['movie', 'music', 'tv', 'celebrity', 'oscar', 'grammy', 'emmy'],
        'science': ['space', 'nasa', 'climate', 'covid', 'vaccine', 'research', 'discovery'],
        'world': ['war', 'conflict', 'international', 'ukraine', 'russia', 'china', 'europe']
    }
    
    for category, keywords in categories.items():
        if any(keyword in question_lower for keyword in keywords):
            return category
            'yes_percentage': 65.0,
            'no_percentage': 35.0,
            'volume': 1500000,
            'volume_24h': 250000,
            'liquidity': 500000,
            'end_date': '2024-12-31',
            'closed': False,
=======


@router.get("/markets")
>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\web\api\predictions.py
            'active': True,
            'created_at': '2024-01-01',
            'tags': ['crypto', 'bitcoin'],
            'image': 'https://example.com/btc.jpg',
            'url': 'https://polymarket.com/event/bitcoin-price-2024',
            'timestamp': datetime.now().isoformat()
        },
        {
            'id': 'election-2024',
            'question': 'Will the 2024 US Presidential Election go to a recount?',
            'description': 'US Presidential Election recount probability',
            'category': 'politics',
            'outcomes': ['Yes', 'No'],
            'yes_price': 0.25,
            'no_price': 0.75,
            'yes_percentage': 25.0,
            'no_percentage': 75.0,
            'volume': 2000000,
            'volume_24h': 300000,
            'liquidity': 750000,
            'end_date': '2024-11-05',
            'closed': False,
            'active': True,
            'created_at': '2024-01-15',
            'tags': ['politics', 'election'],
            'image': 'https://example.com/election.jpg',
            'url': 'https://polymarket.com/event/election-2024',
            'timestamp': datetime.now().isoformat()
        },
        {
            'id': 'super-bowl-2024',
            'question': 'Will the Kansas City Chiefs win Super Bowl 2024?',
            'description': 'NFL Super Bowl 2024 winner prediction',
            'category': 'sports',
            'outcomes': ['Yes', 'No'],
            'yes_price': 0.55,
            'no_price': 0.45,
            'yes_percentage': 55.0,
            'no_percentage': 45.0,
            'volume': 800000,
            'volume_24h': 120000,
            'liquidity': 300000,
            'end_date': '2024-02-11',
            'closed': False,
            'active': True,
            'created_at': '2024-01-20',
            'tags': ['sports', 'nfl', 'super-bowl'],
            'image': 'https://example.com/sb.jpg',
            'url': 'https://polymarket.com/event/super-bowl-2024',
            'timestamp': datetime.now().isoformat()
        },
        {
            'id': 'fed-rate-cut',
            'question': 'Will the Federal Reserve cut interest rates in Q2 2024?',
            'description': 'Federal Reserve interest rate decision for Q2 2024',
            'category': 'finance',
            'outcomes': ['Yes', 'No'],
            'yes_price': 0.40,
            'no_price': 0.60,
            'yes_percentage': 40.0,
            'no_percentage': 60.0,
            'volume': 1200000,
            'volume_24h': 180000,
            'liquidity': 450000,
            'end_date': '2024-06-30',
            'closed': False,
            'active': True,
            'created_at': '2024-02-01',
            'tags': ['finance', 'fed', 'interest-rates'],
            'image': 'https://example.com/fed.jpg',
            'url': 'https://polymarket.com/event/fed-rate-cut',
            'timestamp': datetime.now().isoformat()
        },
        {
            'id': 'ai-agi-2025',
            'question': 'Will AGI be achieved by 2025?',
            'description': 'Artificial General Intelligence timeline prediction',
            'category': 'technology',
            'outcomes': ['Yes', 'No'],
            'yes_price': 0.15,
            'no_price': 0.85,
            'yes_percentage': 15.0,
            'no_percentage': 85.0,
            'volume': 600000,
            'volume_24h': 90000,
            'liquidity': 200000,
            'end_date': '2025-12-31',
            'closed': False,
            'active': True,
            'created_at': '2024-02-10',
            'tags': ['technology', 'ai', 'agi'],
            'image': 'https://example.com/ai.jpg',
            'url': 'https://polymarket.com/event/ai-agi-2025',
            'timestamp': datetime.now().isoformat()
        }
    ]
=======
>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\web\api\predictions.py
=======
>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\web\api\predictions.py
=======
>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\web\api\predictions.py


def categorize_market(question: str) -> str:
    """Categorize prediction market based on question."""
    question_lower = question.lower()
    
    categories = {
        'crypto': ['bitcoin', 'btc', 'ethereum', 'eth', 'crypto', 'blockchain', 'defi', 'nft'],
=======
>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\web\api\predictions.py
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
=======
>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\web\api\predictions.py
=======
>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\web\api\predictions.py
=======
from fastapi import APIRouter

router = APIRouter(prefix="/api/v1/predictions", tags=["predictions"])

@router.get("/markets")
async def get_markets():
    return {"status": "success", "markets": [], "count": 0}

@router.get("/categories")
async def get_categories():
    return {"status": "success", "categories": {}, "total_markets": 0}
>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\web\api\predictions.py
