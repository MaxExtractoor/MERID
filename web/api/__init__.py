"""
MERID API Layer - Institutional-Grade REST Endpoints

Comprehensive API for system control, trading, monitoring, and data access.
"""

# Note: Routers are imported via safe-import (_si) in web.main to handle
# optional/legacy modules gracefully. Direct imports here are for core APIs only.

from web.api.system_control import router as system_router
from web.api.trading import router as trading_router
from web.api.reflection import router as reflection_router
from web.api.streams import router as streams_router
from web.api.live_stream import router as live_stream_router
from web.api.paper_trading import router as paper_trading_router
from web.api.data_endpoints import router as data_router

__all__ = [
    "system_router",
    "trading_router",
    "reflection_router",
    "streams_router",
    "live_stream_router",
    "paper_trading_router",
    "data_router",
]
