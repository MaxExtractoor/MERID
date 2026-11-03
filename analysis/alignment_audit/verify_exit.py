"""Gather exchange evidence for exit_4c396e550d0b43455041 (KXETH15M-26NOV011930-30):
- all fills on the ticker (does an exit fill exist?)
- resting orders (verified empty earlier)
- market status (settled?)
"""
import asyncio, json
from merid.event_venues.kalshi.client import get_kalshi_client

TICKER = 'KXETH15M-26NOV011930-30'
EXIT_COID = 'exit_4c396e550d0b43455041'

async def main():
    c = get_kalshi_client()
    # fills on ticker (REST /portfolio/fills?ticker=)
    try:
        fills = await c.get_fills(ticker=TICKER, limit=50)
        items = fills if isinstance(fills, list) else getattr(fills, 'fills', fills)
        print('=== fills for', TICKER, '===')
        print(json.dumps(items, default=str)[:3000])
    except Exception as e:
        print('fills err:', type(e).__name__, e)
        try:
            print('raw attrs:', [m for m in dir(c) if 'fill' in m.lower() or 'order' in m.lower()])
        except Exception:
            pass
    try:
        mkt = await c.get_market(TICKER)
        print('=== market status ===')
        print(json.dumps(getattr(mkt, '__dict__', mkt), default=str)[:1200])
    except Exception as e:
        print('market err:', type(e).__name__, e)

asyncio.run(main())
