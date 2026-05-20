# merid/kalshi/crypto_rti_api.py
"""Crypto RTI diagnostics API endpoint."""

from typing import Dict, List, Any
from fastapi import APIRouter, Depends
from web.api.auth import get_current_session
from utils.logger import get_logger
import time
import os

logger = get_logger("merid.kalshi.crypto_rti_api")

router = APIRouter(
    prefix="/api/v1/kalshi-grid/crypto",
    tags=["Kalshi Crypto RTI"],
    dependencies=[Depends(get_current_session)],
)


def get_mock_rti_data() -> Dict[str, Any]:
    """Mock RTI data - replace with actual RTI service integration."""
    return {
        "btc": {
            "rti": 1.23,
            "sma_60s": 1.21,
            "vol_ratio": 1.15,
            "vol_spike_events": [
                {"timestamp": time.time() - 3600, "magnitude": 2.1},
                {"timestamp": time.time() - 7200, "magnitude": 1.8},
            ]
        },
        "eth": {
            "rti": 0.89,
            "sma_60s": 0.91,
            "vol_ratio": 0.98,
            "vol_spike_events": [
                {"timestamp": time.time() - 1800, "magnitude": 1.6},
            ]
        },
        "sol": {
            "rti": 1.45,
            "sma_60s": 1.42,
            "vol_ratio": 1.32,
            "vol_spike_events": []
        },
        "xrp": {
            "rti": 0.67,
            "sma_60s": 0.69,
            "vol_ratio": 1.05,
            "vol_spike_events": [
                {"timestamp": time.time() - 900, "magnitude": 1.4},
            ]
        }
    }


@router.get("/rti")
async def get_crypto_rti():
    """Get crypto RTI diagnostics data."""
    try:
        # BUG-FIX: Try to get real RTI data before falling back to mock
        # Priority: 1. Real RTI service, 2. Market data derived, 3. Configurable mock
        
        # Try real RTI service first
        try:
            from merid.data.rti_service import get_rti_service
            rti_service = get_rti_service()
            real_data = await rti_service.get_crypto_rti()
            if real_data:
                return {
                    "data": real_data,
                    "timestamp": time.time(),
                    "source": "rti_service"
                }
        except Exception as exc:
            logger.debug(f"RTI service unavailable, trying market data: {exc}")
        
        # Try to derive from market data
        try:
            from merid.event_venues.kalshi.market_state import get_kalshi_market_state_store
            store = get_kalshi_market_state_store()
            derived_data = {}
            assets = ["btc", "eth", "sol", "xrp", "doge"]
            for asset in assets:
                # Try to get from live market data
                ticker = f"KX{asset.upper()}"
                state = store.get(ticker)
                if state:
                    # BUG-FIX: Made defaults configurable via env vars instead of hardcoded
                    default_mid_price = int(os.getenv("MERID_RTI_DEFAULT_MID_PRICE", "50"))
                    default_vol_ratio = float(os.getenv("MERID_RTI_DEFAULT_VOL_RATIO", "1.0"))
                    derived_data[asset] = {
                        "rti": state.get("mid_price", default_mid_price) / default_mid_price,  # Normalized
                        "sma_60s": state.get("mid_price", default_mid_price) / default_mid_price,
                        "vol_ratio": default_vol_ratio,
                        "vol_spike_events": [],
                        "derived_from": "market_state"
                    }
            if derived_data:
                return {
                    "data": derived_data,
                    "timestamp": time.time(),
                    "source": "market_derived"
                }
        except Exception as exc:
            logger.debug(f"Market data derivation failed: {exc}")
        
        # PRODUCTION SAFETY: Only use mock data in non-production environments
        # BUG-FIX: os already imported at module level, removed nested import
        if os.getenv("MERID_ENV", "development") == "production":
            logger.error("[RTI-FAIL-CLOSED] No RTI service available in production")
            return {
                "data": {},
                "error": "RTI service unavailable",
                "timestamp": time.time(),
                "source": "unavailable"
            }
        
        # Fallback to mock data with clear warning
        logger.warning("[RTI-MOCK-FALLBACK] Using mock RTI data - NOT FOR PRODUCTION")
        data = get_mock_rti_data()
        
        # Add derived metrics
        # BUG-FIX: Made configurable via env var instead of hardcoded 3600 (1 hour)
        # BUG-FIX #36: Removed redundant nested import os - already imported at module level
        lookback_seconds = int(os.getenv("MERID_RTI_VOL_SPIKE_LOOKBACK_SECONDS", "3600"))
        for asset, metrics in data.items():
            metrics["rti_sma_deviation"] = metrics["rti"] - metrics["sma_60s"]
            lookback_ts = time.time() - lookback_seconds
            recent_spikes = [
                spike for spike in metrics["vol_spike_events"]
                if spike["timestamp"] > lookback_ts
            ]
            metrics["recent_vol_spikes"] = len(recent_spikes)
            metrics["max_recent_spike"] = max([s["magnitude"] for s in recent_spikes], default=0)
        
        return {
            "data": data,
            "timestamp": time.time(),
            "source": "mock",
            "warning": "MOCK DATA - NOT FOR PRODUCTION USE"
        }
    except Exception as exc:
        logger.error(f"Failed to get crypto RTI data: {exc}")
        return {
            "data": {},
            "error": str(exc),
            "timestamp": time.time()
        }
