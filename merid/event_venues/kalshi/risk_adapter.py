"""
Risk Adapter — Compatibility shim for legacy Position interface

This module provides a compatibility layer between the new pure-function risk pipeline
and legacy code expecting the old Position/PositionCache interface.

This is a temporary shim to enable gradual migration. All new code should use
the new pipeline directly via risk_pipeline_coordinator.

DEPRECATED: This module will be removed after Q2 2026. Migrate to new pipeline.
"""

from __future__ import annotations

import warnings
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional

from utils.logger import get_logger

from merid.event_venues.kalshi.risk_pipeline_coordinator import get_risk_projection
from merid.event_venues.kalshi.risk_projection import (
    BackendPosition,
    RiskProjection,
)

logger = get_logger("merid.event_venues.kalshi.risk_adapter")

# Deprecation warning
warnings.warn(
    "risk_adapter.py is deprecated. Migrate to risk_pipeline_coordinator directly. "
    "This shim will be removed after Q2 2026.",
    DeprecationWarning,
    stacklevel=2,
)


class LegacyPosition:
    """Legacy Position interface for backward compatibility.
    
    This wraps BackendPosition to provide the old Position interface.
    New code should use BackendPosition directly.
    """
    
    def __init__(self, backend_pos: BackendPosition):
        self._backend = backend_pos
        self.ticker = backend_pos.ticker
        self.side = backend_pos.side
        self.contracts = backend_pos.count
        self.avg_price_cents = int(backend_pos.avg_price_dollars * 100)
        self.unrealized_pnl_usd = float(backend_pos.unrealized_pnl_dollars)
        self.realized_pnl_usd = float(backend_pos.realized_pnl_dollars)
        self.last_updated = backend_pos.created_at
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for legacy API compatibility."""
        return {
            "ticker": self.ticker,
            "side": self.side,
            "contracts": self.contracts,
            "avg_price_cents": self.avg_price_cents,
            "unrealized_pnl_usd": self.unrealized_pnl_usd,
            "realized_pnl_usd": self.realized_pnl_usd,
            "last_updated": self.last_updated.isoformat() if self.last_updated else None,
        }


class LegacyPositionCache:
    """Legacy PositionCache interface for backward compatibility.
    
    This wraps the new risk pipeline to provide the old PositionCache interface.
    New code should use risk_pipeline_coordinator.get_risk_projection() directly.
    """
    
    def __init__(self):
        self._last_sync_time = None
    
    async def get_all_positions(
        self,
        validate_freshness: bool = False,
    ) -> Dict[str, LegacyPosition]:
        """Get all positions from new pipeline.
        
        Args:
            validate_freshness: Ignored (new pipeline always fresh)
            
        Returns:
            Dict mapping ticker to LegacyPosition
        """
        projection = await get_risk_projection()
        self._last_sync_time = projection.backend_timestamp or datetime.now(timezone.utc)
        
        # Convert BackendPosition to LegacyPosition
        legacy_positions = {}
        for ticker, backend_pos in projection.positions_by_ticker.items():
            legacy_positions[ticker] = LegacyPosition(backend_pos)
        
        return legacy_positions
    
    async def get_position(self, ticker: str) -> Optional[LegacyPosition]:
        """Get position for specific ticker.
        
        Args:
            ticker: Market ticker
            
        Returns:
            LegacyPosition or None if not found
        """
        positions = await self.get_all_positions()
        return positions.get(ticker)
    
    async def refresh_positions(self) -> None:
        """Refresh positions from backend (no-op, new pipeline always fresh)."""
        # New pipeline fetches fresh data on each call, no refresh needed
        pass


def get_position_cache() -> LegacyPositionCache:
    """Get legacy position cache singleton (compatibility shim).
    
    DEPRECATED: Use risk_pipeline_coordinator.get_risk_projection() instead.
    """
    return LegacyPositionCache()


async def get_positions_legacy() -> Dict[str, LegacyPosition]:
    """Get positions using legacy interface (compatibility shim).
    
    DEPRECATED: Use risk_pipeline_coordinator.get_risk_projection() instead.
    """
    cache = get_position_cache()
    return await cache.get_all_positions()
