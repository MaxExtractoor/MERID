"""
Execution Package Initialization

Provides unified access to self-hosted execution infrastructure:
- Execution simulator for paper trading
- Venue adapters for swappable broker connections
- Market data ingestion from multiple sources (WebSocket, UDP multicast, FIX)
- Complete execution service with REST/WebSocket API
- Persistent order books with journaling and snapshots
"""

from .simulator import get_execution_simulator, ExecutionSimulator, MarketData, Order, Position, Account
from .venue_adapter import get_venue_manager, VenueManager, VenueAdapter, VenueConfig, VenueType
from .simulator_adapter import create_simulator_adapter, SimulatorVenueAdapter
from .market_data_ingestor import get_market_data_ingestor, MarketDataIngestor, create_binance_websocket_config, create_kraken_websocket_config
from .multicast_feed import get_multicast_feed_manager, MulticastFeedManager, MulticastFeedHandler, create_itch_config, create_soupbin_config
from .fix_feed import get_fix_feed_manager, FIXFeedManager, FIXMarketDataFeed, create_fix_config
from .persistent_book import get_persistent_book_manager, PersistentOrderBookManager, PersistentOrderBook
from .service import get_execution_service, ExecutionService

__all__ = [
    # Core simulator
    "get_execution_simulator",
    "ExecutionSimulator", 
    "MarketData",
    "Order",
    "Position",
    "Account",
    
    # Venue management
    "get_venue_manager",
    "VenueManager",
    "VenueAdapter", 
    "VenueConfig",
    "VenueType",
    
    # Adapters
    "create_simulator_adapter",
    "SimulatorVenueAdapter",
    
    # Market data - WebSocket/REST
    "get_market_data_ingestor",
    "MarketDataIngestor",
    "create_binance_websocket_config",
    "create_kraken_websocket_config",
    
    # Market data - UDP multicast
    "get_multicast_feed_manager",
    "MulticastFeedManager",
    "MulticastFeedHandler",
    "create_itch_config",
    "create_soupbin_config",
    
    # Market data - FIX
    "get_fix_feed_manager",
    "FIXFeedManager",
    "FIXMarketDataFeed",
    "create_fix_config",
    
    # Persistent order books
    "get_persistent_book_manager",
    "PersistentOrderBookManager",
    "PersistentOrderBook",
    
    # Service
    "get_execution_service",
    "ExecutionService"
]
