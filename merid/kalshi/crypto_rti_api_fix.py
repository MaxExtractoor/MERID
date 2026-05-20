# merid/kalshi/crypto_rti_api.py
"""Crypto RTI diagnostics API endpoint."""

from typing import Dict, List, Any
from fastapi import APIRouter, Depends
from web.api.auth import get_current_session
from utils.logger import get_logger
import time
import os

logger = get_logger(__name__)
router = APIRouter()


@router.get("/api/v1/crypto-rti/diagnostics")
async def get_crypto_rti_diagnostics(
    current_user: dict = Depends(get_current_session),
) -> Dict[str, Any]:
    """Return RTI diagnostics for all tracked crypto assets."""
    from merid.event_venues.kalshi.market_state import get_kalshi_market_state_store
    from merid.kalshi.macro_overlay import get_macro_overlay
    
    store = get_kalshi_market_state_store()
    macro = get_macro_overlay()
    
    # BUG-FIX #35: Added DOGE to complete the 5-asset crypto list
    assets = ["btc", "eth", "sol", "xrp", "doge"]
    
    diagnostics = {
        "timestamp": time.time(),
        "assets": {},
        "macro_overlay": {},
        "derived_rti": {},
    }
    
    for asset in assets:
        state = store.get_state(asset)
        if state:
            diagnostics["assets"][asset] = {
                "ticker": state.ticker,
                "mid_price": state.mid_price,
                "bid": state.bid,
                "ask": state.ask,
                "spread": state.ask - state.bid if state.ask and state.bid else None,
                "last_update": state.last_update,
            }
    
    # Macro overlay status
    diagnostics["macro_overlay"] = {
        "active": macro.active,
        "current_score": macro.current_score,
        "applied_discount": macro.applied_discount,
    }
    
    # Derived RTI from market state
    derived_data = {}
    for asset in assets:
        state = store.get_state(asset)
        if state:
            # BUG-FIX: Made defaults configurable via env vars instead of hardcoded
            default_mid_price = int(os.getenv("MERID_RTI_DEFAULT_MID_PRICE", "50"))
            default_vol_ratio = float(os.getenv("MERID_RTI_DEFAULT_VOL_RATIO", "1.0"))
            derived_data[asset] = {
                "rti": state.get("mid_price", default_mid_price) / default_mid_price,
                "sma_60s": state.get("mid_price", default_mid_price) / default_mid_price,
                "vol_ratio": default_vol_ratio,
                "vol_spike_events": [],
                "derived_from": "market_state"
            }
    
    # BUG-FIX #36: Removed redundant nested import os - already imported at module level
    # (Previously had: import os here which was redundant)
    
    diagnostics["derived_rti"] = derived_data
    
    return diagnostics


@router.get("/api/v1/crypto-rti/summary")
async def get_crypto_rti_summary(
    current_user: dict = Depends(get_current_session),
) -> Dict[str, Any]:
    """Return summarized RTI status for quick health checks."""
    from merid.event_venues.kalshi.market_state import get_kalshi_market_state_store
    
    store = get_kalshi_market_state_store()
    # BUG-FIX #35: Added DOGE here too
    assets = ["btc", "eth", "sol", "xrp", "doge"]
    
    healthy_count = 0
    stale_count = 0
    
    for asset in assets:
        state = store.get_state(asset)
        if state and state.is_fresh():
            healthy_count += 1
        else:
            stale_count += 1
    
    return {
        "total_tracked": len(assets),
        "healthy": healthy_count,
        "stale": stale_count,
        "status": "healthy" if healthy_count == len(assets) else "degraded",
    }
