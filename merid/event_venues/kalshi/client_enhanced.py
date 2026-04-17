"""
Re-export from legacy location for backward compatibility.
"""
from merid.event_venues.kalshi.legacy.client_enhanced import (
    EnhancedKalshiClient,
    create_enhanced_client,
    wrap_client,
)

__all__ = ["EnhancedKalshiClient", "create_enhanced_client", "wrap_client"]
