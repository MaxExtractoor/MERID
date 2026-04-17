"""
MERID Event Venues Package

Unified interface for prediction market venues (Kalshi-only in production)
LEGACY: Polymarket support moved to _legacy/polymarket/
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
# LEGACY: Polymarket imports moved to _legacy/polymarket/
# POLYMARKET IMPORTS REMOVED - see _legacy folder

# Register Kalshi venue client with factory
VenueClientFactory.register("kalshi", KalshiVenueClient)

# LEGACY: Polymarket registration preserved in _legacy
# VenueClientFactory.register("polymarket", PolymarketVenueClient)

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
    # LEGACY: Polymarket exports removed - see _legacy/polymarket/
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
