"""Spot Debug API - Observability endpoint for UnifiedSpotService.

Provides debug information about spot price sources, health, and performance.
"""

from fastapi import APIRouter
from typing import Dict, Any

router = APIRouter(prefix="/spot", tags=["spot"])


@router.get("/prices")
async def get_spot_prices() -> Dict[str, Any]:
    """Get current spot prices from UnifiedSpotService.
    
    Returns:
        - assets: Dictionary of current prices for all supported assets
        - timestamp: Last update timestamp
        - source: Price source information
        - count: Number of assets with valid prices
    """
    try:
        from data.unified_spot_service import get_unified_spot_service
        
        unified = get_unified_spot_service()
        
        # Get current prices for all assets
        prices = unified.get_all_prices()
        
        # Format response
        assets_dict = {}
        for asset, price_data in prices.items():
            assets_dict[asset] = {
                "price": price_data.get("price"),
                "source": price_data.get("source"),
                "timestamp": price_data.get("timestamp"),
                "confidence": price_data.get("confidence", 1.0)
            }
        
        return {
            "assets": assets_dict,
            "timestamp": unified.get_last_update_timestamp() if hasattr(unified, 'get_last_update_timestamp') else None,
            "source": "unified_spot_service",
            "count": len(assets_dict)
        }
        
    except Exception as e:
        return {
            "assets": {},
            "timestamp": None,
            "source": "unified_spot_service",
            "count": 0,
            "error": str(e)
        }


@router.get("/debug")
async def get_spot_debug() -> Dict[str, Any]:
    """Get debug snapshot from UnifiedSpotService.
    
    Returns:
        - running: Whether streaming is active
        - cache: Current cached prices with metadata
        - fetch_counts: Per-asset fetch counts
        - fallback_counts: Per-asset fallback counts
        - supported_assets: List of supported assets
    """
    try:
        from data.unified_spot_service import get_unified_spot_service
        
        unified = get_unified_spot_service()
        snapshot = unified.get_debug_snapshot()
        
        return snapshot
        
    except Exception as e:
        return {
            "error": str(e),
            "running": False,
            "cache": {},
            "fetch_counts": {},
            "fallback_counts": {},
            "supported_assets": [],
        }
