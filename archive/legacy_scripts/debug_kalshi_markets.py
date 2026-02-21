"""Debug Kalshi market data structure."""
import asyncio

async def debug_markets():
    from merid.event_venues.kalshi.client import KalshiVenueClient
    from merid.event_venues.kalshi.models import KalshiConfig
    from merid.event_venues.base import MarketFilter
    
    client = KalshiVenueClient(KalshiConfig())
    markets = await client.list_markets(MarketFilter(active_only=True, limit=5))
    
    print(f"\nFetched {len(markets)} sample markets\n")
    
    for i, m in enumerate(markets[:3]):
        print(f"Market {i+1}:")
        print(f"  market_id: {m.market_id}")
        print(f"  question: {m.question[:80] if m.question else None}")
        print(f"  category: {m.category}")
        print(f"  description: {m.description[:80] if m.description else None}")
        print(f"  active: {m.active}")
        print(f"  end_date: {m.end_date}")
        print()

asyncio.run(debug_markets())
