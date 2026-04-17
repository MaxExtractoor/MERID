"""
MERID API Layer - Institutional-Grade REST Endpoints

Comprehensive API for system control, trading, monitoring, and data access.
"""

from web.api.institutional import router as institutional_router
from web.api.system_control import router as system_router
from web.api.trading import router as trading_router
from web.api.reflection import router as reflection_router
from web.api.streams import router as streams_router
from web.api.live_stream import router as live_stream_router
from web.api.betting import router as betting_router
from web.api.paper_trading import router as paper_trading_router
from web.api.data_endpoints import router as data_router
# Removed - trading_suite loads paper adapter which instantiates at module level
# from web.api.trading_suite import router as trading_suite_router

__all__ = [
    "institutional_router",
    "system_router",
    "trading_router",
    "reflection_router",
    "streams_router",
    "live_stream_router",
    "betting_router",
    "paper_trading_router",
    "data_router",
    # "trading_suite_router",  # Removed - causes crypto exchange init
]
