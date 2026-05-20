"""FVG API — Fair Value Gap signals and statistics.

Endpoints:
- GET /api/v1/fvg/signals/{ticker} — FVG signal for a specific market
- GET /api/v1/fvg/stats — Aggregate FVG statistics across all assets
- GET /api/v1/fvg/config — FVG configuration and parameters
"""

from __future__ import annotations

import time
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException

from merid.prediction.fvg_integration import (
    get_fvg_integrator,
    get_fvg_signal_for_market,
    is_fvg_enabled,
)
from merid.prediction.forecasters.fvg import get_fvg_store
from utils.logger import get_logger

logger = get_logger("web.api.fvg")

router = APIRouter(prefix="/api/v1/fvg", tags=["fvg"])


@router.get("/signals/{ticker}")
async def get_fvg_signal(ticker: str) -> Dict[str, Any]:
    """Get FVG signal for a specific Kalshi market ticker.
    
    Returns:
        - direction: "bullish", "bearish", or "neutral"
        - confidence: 0.0-1.0 signal confidence
        - nearest_fvg_distance: cents to nearest unfilled FVG
        - active_fvgs: count of active FVGs for this market
        - confluence_score: cross-timeframe alignment (-1.0 to 1.0)
        - fill_imminent: True if price is within fill threshold
    """
    if not is_fvg_enabled():
        raise HTTPException(status_code=503, detail="FVG analysis is disabled")
    
    # Get market state to extract bid/ask
    from merid.event_venues.kalshi.market_state import get_kalshi_market_state_store
    store = get_kalshi_market_state_store()
    state = store.get(ticker)
    
    if not state:
        raise HTTPException(status_code=404, detail=f"Market {ticker} not found")
    
    if state.best_bid_cents is None or state.best_ask_cents is None:
        raise HTTPException(status_code=404, detail=f"No orderbook data for {ticker}")
    
    bid = state.best_bid_cents / 100.0
    ask = state.best_ask_cents / 100.0
    
    signal = get_fvg_signal_for_market(ticker, bid, ask)
    
    if not signal:
        return {
            "ticker": ticker,
            "direction": "neutral",
            "confidence": 0.0,
            "active_fvgs": 0,
            "fill_imminent": False,
            "error": "No FVG signal available",
        }
    
    return signal.to_dict()


@router.get("/stats")
async def get_fvg_stats(asset: Optional[str] = None) -> Dict[str, Any]:
    """Get aggregate FVG statistics.
    
    Args:
        asset: Optional asset filter (BTC, ETH, SOL, XRP, DOGE)
    
    Returns:
        - enabled: Whether FVG analysis is enabled
        - tracked_tickers: Number of tickers being tracked
        - by_asset: Breakdown per asset
        - active_fvgs_total: Total active FVGs across all assets
    """
    integrator = get_fvg_integrator()
    fvg_store = get_fvg_store()
    
    stats = integrator.get_stats()
    
    # Count total active FVGs
    total_fvgs = 0
    for asset_code in ["BTC", "ETH", "SOL", "XRP", "DOGE"]:
        for tf in ["15m", "1h", "4h", "daily"]:
            total_fvgs += len(fvg_store.get_active_fvgs(asset_code, tf))
    
    stats["active_fvgs_total"] = total_fvgs
    
    if asset:
        # Filter to specific asset
        asset_stats = stats.get("by_asset", {}).get(asset.upper(), {})
        asset_fvgs = 0
        for tf in ["15m", "1h", "4h", "daily"]:
            asset_fvgs += len(fvg_store.get_active_fvgs(asset.upper(), tf))
        
        return {
            "asset": asset.upper(),
            "enabled": stats["enabled"],
            "tracked_tickers": asset_stats.get("tickers", 0),
            "active_fvgs": asset_fvgs,
            "tickers_with_fvgs": [
                {"ticker": t, "count": len(fvg_store.get_active_fvgs(asset.upper(), tf))}
                for t in stats.get("tracked_tickers", [])
                for tf in ["15m"]
            ],
        }
    
    return stats


@router.get("/config")
async def get_fvg_config() -> Dict[str, Any]:
    """Get FVG configuration and parameters."""
    import os
    
    return {
        "enabled": is_fvg_enabled(),
        "window_size": int(os.getenv("MERID_FVG_WINDOW_SIZE", "20")),
        "min_gap_cents": float(os.getenv("MERID_FVG_MIN_GAP_CENTS", "2.0")),
        "fill_threshold_cents": float(os.getenv("MERID_FVG_FILL_THRESHOLD", "5.0")),
        "atr_period": int(os.getenv("MERID_FVG_ATR_PERIOD", "14")),
        "min_price_change_cents": float(os.getenv("MERID_FVG_MIN_PRICE_CHANGE", "0.5")),
    }


@router.get("/fvgs/{asset}/{timeframe}")
async def get_active_fvgs(asset: str, timeframe: str) -> Dict[str, Any]:
    """Get all active (unfilled) FVGs for an asset and timeframe.
    
    Args:
        asset: Asset code (BTC, ETH, SOL, XRP, DOGE)
        timeframe: Timeframe (15m, 1h, 4h, daily)
    
    Returns:
        List of active FVGs with their properties.
    """
    if not is_fvg_enabled():
        raise HTTPException(status_code=503, detail="FVG analysis is disabled")
    
    store = get_fvg_store()
    fvgs = store.get_active_fvgs(asset.upper(), timeframe.lower())
    
    return {
        "asset": asset.upper(),
        "timeframe": timeframe.lower(),
        "count": len(fvgs),
        "fvgs": [
            {
                "direction": f.direction,
                "top": f.top,
                "bottom": f.bottom,
                "size": f.size,
                "created_at": f.created_at,
                "age_seconds": time.time() - f.created_at,
            }
            for f in fvgs
        ],
    }
