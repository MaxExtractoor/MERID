"""
Kalshi Venue API Routes

Unified API endpoints for Kalshi venue integration.
Gracefully degrades when KalshiVenueAPI is unavailable.
"""

from fastapi import APIRouter, HTTPException
from typing import Dict, Any, Optional
from datetime import datetime

from utils.logger import get_logger

logger = get_logger("web.api.kalshi_venue_routes")

router = APIRouter()

# Global API instance
_kalshi_api: Optional[Any] = None
_kalshi_api_error: Optional[str] = None


async def get_kalshi_api():
    global _kalshi_api, _kalshi_api_error
    if _kalshi_api is not None:
        return _kalshi_api
    if _kalshi_api_error is not None:
        raise RuntimeError(_kalshi_api_error)
    try:
        from create_kalshi_venue_api import KalshiVenueAPI
        _kalshi_api = KalshiVenueAPI()
        await _kalshi_api.initialize()
        return _kalshi_api
    except Exception as exc:
        _kalshi_api_error = f"KalshiVenueAPI unavailable: {exc}"
        logger.warning("kalshi_venue_api_init_failed: %s", exc)
        raise RuntimeError(_kalshi_api_error) from exc


def _degraded_venue_status() -> Dict[str, Any]:
    """Return a safe degraded response instead of 500 for /crypto/status."""
    return {
        "venue_id": "kalshi",
        "status": "degraded",
        "crypto_available": False,
        "total_markets": 0,
        "crypto_markets": 0,
        "last_checked": datetime.now().isoformat(),
        "error_type": "api_unavailable",
        "error_message": _kalshi_api_error or "KalshiVenueAPI not initialized",
        "connectivity": {
            "primary_endpoint": {"url": "", "status": "error"},
            "fallback_endpoint": {"url": "", "status": "error"},
        },
        "capabilities": [],
    }


@router.get("/crypto/status")
async def get_crypto_market_status():
    """Get authoritative crypto market status from Kalshi venue"""
    try:
        api = await get_kalshi_api()
        result = await api.get_crypto_status()
        return result
    except Exception as e:
        logger.debug("crypto_status degraded: %s", e)
        return _degraded_venue_status()


@router.get("/markets/kalshi")
async def get_kalshi_markets():
    """Get normalized Kalshi market catalog"""
    try:
        api = await get_kalshi_api()
        result = await api.get_kalshi_markets()
        return result
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Failed to get markets: {str(e)}")


@router.get("/markets/kalshi/crypto")
async def get_kalshi_crypto_markets():
    """Get Kalshi crypto markets only"""
    try:
        api = await get_kalshi_api()
        result = await api.get_crypto_markets_only()
        return result
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Failed to get crypto markets: {str(e)}")


@router.post("/venues/kalshi/cycle")
async def run_kalshi_crypto_cycle():
    """Trigger Kalshi crypto bot cycle"""
    try:
        api = await get_kalshi_api()
        result = await api.run_scheduler_cycle()
        return result
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Cycle execution failed: {str(e)}")


@router.get("/venues")
async def get_venues_info():
    """Get venue registry and routing information"""
    try:
        api = await get_kalshi_api()
        result = await api.get_venues_info()
        return result
    except Exception as e:
        return {
            "venues": {},
            "capabilities": {},
            "error": f"Venue registry unavailable: {str(e)}",
        }
