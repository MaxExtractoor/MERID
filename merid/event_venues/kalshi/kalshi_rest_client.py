"""Kalshi REST Client Wrapper

Provides a standardized interface for REST API calls to Kalshi.
This module wraps the existing KalshiClientV2 for fills and portfolio operations.
"""

from __future__ import annotations
import os
from typing import Any, Dict, List, Optional
from datetime import datetime, timezone

from utils.logger import get_logger

logger = get_logger("merid.event_venues.kalshi.kalshi_rest_client")


class KalshiRestClient:
    """REST client wrapper for Kalshi API.
    
    Provides methods for fetching fills and portfolio data via REST,
    used primarily for reconciliation and backfill operations.
    """
    
    def __init__(self):
        self._client = None
        self._initialized = False
    
    async def _ensure_client(self):
        """Lazy initialization of the underlying client."""
        if not self._initialized:
            from merid.event_venues.kalshi.client import KalshiVenueClient
            from merid.event_venues.kalshi.kalshi_config import get_kalshi_config
            config = get_kalshi_config()
            self._client = KalshiVenueClient(config)
            self._initialized = True
        return self._client
    
    async def get_fills(
        self,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        limit: int = 100,
        cursor: Optional[str] = None
    ) -> Dict[str, Any]:
        """Fetch fills from Kalshi REST API.
        
        Args:
            start_time: Filter fills after this time (UTC)
            end_time: Filter fills before this time (UTC)
            limit: Maximum number of fills to return
            cursor: Pagination cursor from previous request
            
        Returns:
            Dict with 'fills' list and optional 'cursor' for pagination
        """
        try:
            client = await self._ensure_client()
            
            # Convert times to ISO format if provided
            params = {"limit": limit}
            if start_time:
                params["start_time"] = start_time.isoformat()
            if end_time:
                params["end_time"] = end_time.isoformat()
            if cursor:
                params["cursor"] = cursor
            
            # Call the Kalshi API
            # Convert start_time/end_time to timestamp for client.get_fills
            since_ts = None
            if start_time:
                since_ts = int(start_time.timestamp() * 1000)
            
            result = await client.get_fills(limit=limit, since_ts=since_ts)
            
            if not result.success:
                raise Exception(f"Failed to fetch fills: {result.error}")
            
            return {
                "fills": result.data or [],
                "cursor": None  # Original client doesn't return cursor
            }
        except Exception as e:
            logger.error("Failed to fetch fills: %s", e)
            return {"fills": [], "cursor": None}

    async def get_positions_with_filters(
        self,
        filters: Optional[Dict[str, Any]] = None,
        limit: int = 200,
    ):
        """Fetch portfolio positions from Kalshi REST API.

        Delegates to KalshiVenueClient.get_positions_with_filters.
        Returns OperationResult with data containing market_positions/event_positions.
        """
        client = await self._ensure_client()
        return await client.get_positions_with_filters(filters=filters or {}, limit=limit)

    async def get_recent_fills(
        self,
        minutes: int = 5,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """Fetch recent fills from the last N minutes.
        
        Args:
            minutes: Number of minutes back to fetch fills
            limit: Maximum number of fills to return
            
        Returns:
            List of fill dictionaries
        """
        from datetime import datetime, timezone, timedelta
        
        end_time = datetime.now(timezone.utc)
        start_time = end_time - timedelta(minutes=minutes)
        
        result = await self.get_fills(
            start_time=start_time,
            end_time=end_time,
            limit=limit
        )
        
        return result.get("fills", [])


# Singleton instance
_rest_client: Optional[KalshiRestClient] = None


async def get_kalshi_rest_client() -> KalshiRestClient:
    """Get or create the singleton KalshiRestClient instance."""
    global _rest_client
    if _rest_client is None:
        _rest_client = KalshiRestClient()
    return _rest_client
