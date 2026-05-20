"""Alpaca executor stub for risk_routes compatibility.

This is a minimal stub to satisfy imports from web.api.risk_routes.
Full implementation is in trading.adapters.alpaca.
"""
from __future__ import annotations

from typing import Optional, Dict, Any
from dataclasses import dataclass


@dataclass
class AlpacaOrder:
    """Minimal Alpaca order representation."""
    symbol: str
    qty: float
    side: str
    order_type: str = "market"
    status: str = "pending"


class AlpacaExecutor:
    """Stub Alpaca executor for import compatibility."""
    
    def __init__(self, api_key: Optional[str] = None, api_secret: Optional[str] = None):
        self.api_key = api_key
        self.api_secret = api_secret
        self._paper = True
        self._connected = False
    
    async def connect(self) -> bool:
        """Stub connect method."""
        self._connected = True
        return True
    
    async def submit_order(self, symbol: str, qty: float, side: str, 
                          order_type: str = "market") -> AlpacaOrder:
        """Stub order submission."""
        return AlpacaOrder(
            symbol=symbol,
            qty=qty,
            side=side,
            order_type=order_type,
            status="accepted"
        )
    
    async def get_positions(self) -> Dict[str, Any]:
        """Stub positions retrieval."""
        return {}
    
    async def close(self) -> None:
        """Stub cleanup."""
        self._connected = False


# Legacy alias for compatibility
def get_alpaca_executor() -> AlpacaExecutor:
    """Factory function for AlpacaExecutor."""
    import os
    return AlpacaExecutor(
        api_key=os.getenv("ALPACA_API_KEY") or os.getenv("MERID_ALPACA_API_KEY"),
        api_secret=os.getenv("ALPACA_API_SECRET") or os.getenv("MERID_ALPACA_API_SECRET")
    )
