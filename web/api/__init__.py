"""
MERID API Layer - Institutional-Grade REST Endpoints

Comprehensive API for system control, trading, monitoring, and data access.
"""

# Router names are imported lazily so that importing any single submodule
# (e.g. web.api.missing_endpoints) does NOT trigger the full heavyweight
# dependency chain of every other router at package-init time.

_ROUTER_MAP = {
    "institutional_router": ("web.api.institutional", "router"),
    "system_router": ("web.api.system_control", "router"),
    "trading_router": ("web.api.trading", "router"),
    "mining_router": ("web.api.mining", "router"),
    "reflection_router": ("web.api.reflection", "router"),
    "streams_router": ("web.api.streams", "router"),
    "live_stream_router": ("web.api.live_stream", "router"),
    "betting_router": ("web.api.betting", "router"),
    "paper_trading_router": ("web.api.paper_trading", "router"),
    "data_router": ("web.api.data_endpoints", "router"),
}

__all__ = list(_ROUTER_MAP.keys())


def __getattr__(name: str):
    if name in _ROUTER_MAP:
        import importlib
        module_path, attr = _ROUTER_MAP[name]
        mod = importlib.import_module(module_path)
        return getattr(mod, attr)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
