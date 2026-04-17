# merid/kalshi/crypto_rti_api.py
"""Crypto RTI diagnostics API endpoint."""

from typing import Dict, List, Any
from fastapi import APIRouter, Depends
from web.api.auth import get_current_session
from utils.logger import get_logger
import time

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
        # TODO: Integrate with actual RTI service
        data = get_mock_rti_data()
        
        # Add derived metrics
        for asset, metrics in data.items():
            # RTI deviation from SMA
            metrics["rti_sma_deviation"] = metrics["rti"] - metrics["sma_60s"]
            
            # Recent vol spike (last hour)
            one_hour_ago = time.time() - 3600
            recent_spikes = [
                spike for spike in metrics["vol_spike_events"]
                if spike["timestamp"] > one_hour_ago
            ]
            metrics["recent_vol_spikes"] = len(recent_spikes)
            metrics["max_recent_spike"] = max([s["magnitude"] for s in recent_spikes], default=0)
        
        return {
            "data": data,
            "timestamp": time.time(),
            "source": "mock"  # Change to "rti_service" when integrated
        }
    except Exception as exc:
        logger.error(f"Failed to get crypto RTI data: {exc}")
        return {
            "data": {},
            "error": str(exc),
            "timestamp": time.time()
        }
