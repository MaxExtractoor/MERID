"""
Market Data API — watchlist, snapshot, and WebSocket streaming endpoints.

Provides:
- GET  /api/market/snapshot?symbol=BTC/USDT — single instrument snapshot
- GET  /api/market/watchlist — all watchlist instruments
- POST /api/market/watchlist/add — add symbol to watchlist
- POST /api/market/watchlist/remove — remove symbol from watchlist
- WS   /ws/market/{symbol} — real-time price stream (stub, pairs with LightweightPriceChart)
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect
from pydantic import BaseModel
from merid.web.api.auth import get_current_session
from utils.logger import get_logger

logger = get_logger("web.api.market_data")

router = APIRouter(prefix="/api/market", tags=["market-data"], dependencies=[Depends(get_current_session)]  # ZT6-01
)


class WatchlistModifyRequest(BaseModel):
    symbol: str


@router.get("/snapshot")
async def get_snapshot(
    symbol: str = Query(..., description="Symbol like BTC/USDT"),
) -> Dict[str, Any]:
    """Get a single instrument snapshot."""
    try:
        # LEGACY REMOVAL: merid.core.market_data_dxfeed is legacy code
        # from merid.core.market_data_dxfeed import get_dxfeed_adapter
        # adapter = get_dxfeed_adapter()
        # tick = adapter.get_snapshot(symbol)
        # return {"snapshot": tick.to_dict()}
        # For 15m stack, this endpoint is not applicable (uses unified spot service instead)
        raise HTTPException(status_code=501, detail="Market data snapshot not available in 15m stack - use unified spot service")
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("snapshot_error", symbol=symbol, error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/watchlist")
async def get_watchlist() -> Dict[str, Any]:
    """Get snapshots for all watchlist symbols."""
    try:
        # LEGACY REMOVAL: merid.core.market_data_dxfeed is legacy code
        # adapter = get_dxfeed_adapter()
        # ticks = adapter.get_watchlist()
        # return {
        #     "instruments": [t.to_dict() for t in ticks],
        #     "count": len(ticks),
        # }
        # For 15m stack, this endpoint is not applicable (uses unified spot service instead)
        raise HTTPException(status_code=501, detail="Market data watchlist not available in 15m stack - use unified spot service")
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("watchlist_error", error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/watchlist/add")
async def add_to_watchlist(req: WatchlistModifyRequest) -> Dict[str, Any]:
    """Add a symbol to the watchlist."""
    try:
        # LEGACY REMOVAL: merid.core.market_data_dxfeed is legacy code
        # adapter = get_dxfeed_adapter()
        # adapter.add_symbol(req.symbol)
        # return {"success": True, "symbol": req.symbol, "watchlist_size": len(adapter.watchlist_symbols)}
        # For 15m stack, this endpoint is not applicable (uses unified spot service instead)
        raise HTTPException(status_code=501, detail="Market data watchlist not available in 15m stack - use unified spot service")
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("watchlist_add_error", error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/watchlist/remove")
async def remove_from_watchlist(req: WatchlistModifyRequest) -> Dict[str, Any]:
    """Remove a symbol from the watchlist."""
    try:
        # LEGACY REMOVAL: merid.core.market_data_dxfeed is legacy code
        # adapter = get_dxfeed_adapter()
        # adapter.remove_symbol(req.symbol)
        # return {"success": True, "symbol": req.symbol, "watchlist_size": len(adapter.watchlist_symbols)}
        # For 15m stack, this endpoint is not applicable (uses unified spot service instead)
        raise HTTPException(status_code=501, detail="Market data watchlist not available in 15m stack - use unified spot service")
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("watchlist_remove_error", error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc))


# ── WebSocket streaming endpoint ─────────────────────────────────────
#
# Pairs with LightweightPriceChart.tsx on the frontend.
# When dxFeed credentials are available, this will forward real ticks.
# For now, it polls the adapter snapshot at a configurable interval.

ws_router = APIRouter(tags=["market-data-ws"], dependencies=[Depends(get_current_session)]  # ZT6-01
)

_WS_POLL_INTERVAL_S = 1.0  # seconds between pushes (upgrade to tick-driven later)


@ws_router.websocket("/ws/market/{symbol}")
async def ws_market_stream(websocket: WebSocket, symbol: str):
    """
    Real-time price stream for a single instrument.

    Sends JSON messages: { time, open, high, low, close, volume }
    Compatible with TradingView Lightweight Charts candlestick series.
    """
    await websocket.accept()
    logger.info("ws_market_connect", symbol=symbol)

    try:
        # LEGACY REMOVAL: merid.core.market_data_dxfeed is legacy code
        # adapter = get_dxfeed_adapter()
        # adapter.add_symbol(symbol)
        # For 15m stack, this endpoint is not applicable (uses unified spot service instead)
        await websocket.close(code=1001, reason="Market data streaming not available in 15m stack - use unified spot service")
        return
    except Exception as exc:
        logger.error("ws_market_error", symbol=symbol, error=str(exc))
        await websocket.close(code=1011, reason=str(exc))

    except WebSocketDisconnect:
        logger.info("ws_market_disconnect", symbol=symbol)
    except Exception as exc:
        logger.error("ws_market_error", symbol=symbol, error=str(exc))
        try:
            await websocket.close(code=1011, reason=str(exc))
        except Exception as exc:
            logger.debug("async_op_suppressed", error=str(exc))
