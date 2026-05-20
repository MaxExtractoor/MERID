"""Pricing module for MERID trading system.

DYNAMIC PRICING v10 (2026-04-26):
- Real-time WebSocket-driven max contract pricing
- ATR-based volatility scaling
- Time-to-expiration decay
- Spread-based efficiency adjustment
"""

from .dynamic_max_price import (
    DynamicMaxPriceCalculator,
    calculate_dynamic_max_price,
    get_dynamic_max_price_calculator,
    WSOrderbookSnapshot,
)

__all__ = [
    "DynamicMaxPriceCalculator",
    "calculate_dynamic_max_price",
    "get_dynamic_max_price_calculator",
    "WSOrderbookSnapshot",
]
