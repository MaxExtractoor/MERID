"""MERID Services Module.

Provides centralized services for:
- Volatility calculation and caching
- Market data aggregation
- Risk metric computation

Usage:
    from merid.services import get_volatility_service
    
    vol_service = get_volatility_service()
    estimate = await vol_service.get_volatility("BTC", "15m")
"""

from __future__ import annotations

# Defer heavy imports to avoid cold-start penalty
_LAZY_IMPORTS = {
    "VolatilityService": "merid.services.volatility_service",
    "get_volatility_service": "merid.services.volatility_service",
}


def __getattr__(name: str):
    """Lazy import helper to avoid cold-start penalty."""
    if name in _LAZY_IMPORTS:
        import importlib
        mod = importlib.import_module(_LAZY_IMPORTS[name])
        return getattr(mod, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "VolatilityService",
    "get_volatility_service",
]
