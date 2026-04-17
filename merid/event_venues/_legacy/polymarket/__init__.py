"""Polymarket venue package for MERID (LEGACY — no longer active).

Polymarket support was removed; this stub prevents ImportError if anything
still references the _legacy.polymarket path.
"""

try:
    from merid.event_venues.polymarket.client import PolymarketVenueClient
    from merid.event_venues.polymarket.models import (
        Market,
        MarketOutcome,
        Order,
        OrderBook,
        PolymarketConfig,
        Position,
        Trade,
    )
    from merid.event_venues.polymarket.trading import PolymarketTrader
    from merid.event_venues.polymarket.ws import PolymarketWebSocket
except ImportError:
    pass

__all__: list = []
