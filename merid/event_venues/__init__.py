"""
MERID Event Venues Package

Unified interface for prediction market venues (Polymarket, Kalshi, etc.)
"""

from merid.event_venues.base import (
    EventMarket,
    EventOutcome,
    EventVenueClient,
    EventVenueStream,
    MarketFilter,
    PlacedOrder,
    QuoteEvent,
    VenueClientFactory,
    VenueOrder,
    VenueOrderBook,
    VenuePosition,
    VenueTrade,
)
from merid.event_venues.kalshi import (
    KalshiBalance,
    KalshiConfig,
    KalshiMarket,
    KalshiOrder,
    KalshiOrderBook,
    KalshiOutcome,
    KalshiPosition,
    KalshiTrader,
    KalshiTrade,
    KalshiVenueClient,
    KalshiWebSocket,
)
from merid.event_venues.polymarket import (
    Market,
    MarketOutcome,
    Order,
    OrderBook,
    PolymarketConfig,
    PolymarketTrader,
    PolymarketVenueClient,
    PolymarketWebSocket,
    Position,
    Trade,
)

# Register venue clients with factory
VenueClientFactory.register("polymarket", PolymarketVenueClient)
VenueClientFactory.register("kalshi", KalshiVenueClient)

__all__ = [
    # Base interfaces
    "EventVenueClient",
    "EventVenueStream",
    "EventMarket",
    "EventOutcome",
    "MarketFilter",
    "PlacedOrder",
    "VenueOrder",
    "VenueOrderBook",
    "VenuePosition",
    "VenueTrade",
    "QuoteEvent",
    "VenueClientFactory",
    # Polymarket
    "PolymarketVenueClient",
    "PolymarketWebSocket",
    "PolymarketTrader",
    "PolymarketConfig",
    "Market",
    "MarketOutcome",
    "Order",
    "OrderBook",
    "Position",
    "Trade",
    # Kalshi
    "KalshiVenueClient",
    "KalshiWebSocket",
    "KalshiTrader",
    "KalshiConfig",
    "KalshiMarket",
    "KalshiOutcome",
    "KalshiOrder",
    "KalshiOrderBook",
    "KalshiPosition",
    "KalshiTrade",
    "KalshiBalance",
]
