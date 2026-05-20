"""Spot Debug API - Observability endpoint for UnifiedSpotService.

Provides debug information about spot price sources, health, and performance.
"""

from fastapi import APIRouter
from typing import Dict, Any

router = APIRouter(prefix="/api/v1/spot", tags=["spot"])


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
