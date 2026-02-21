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

from fastapi import APIRouter, HTTPException, Query, WebSocket, WebSocketDisconnect
from pydantic import BaseModel
from utils.logger import get_logger

logger = get_logger("web.api.market_data")

router = APIRouter(prefix="/api/market", tags=["market-data"])


class WatchlistModifyRequest(BaseModel):
    symbol: str


@router.get("/snapshot")
async def get_snapshot(
    symbol: str = Query(..., description="Symbol like BTC/USDT"),
) -> Dict[str, Any]:
    """Get a single instrument snapshot."""
    try:
        from core.market_data_dxfeed import get_dxfeed_adapter
        adapter = get_dxfeed_adapter()
        tick = adapter.get_snapshot(symbol)
        return {"snapshot": tick.to_dict()}
    except Exception as exc:
        logger.error("snapshot_error", symbol=symbol, error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/watchlist")
async def get_watchlist() -> Dict[str, Any]:
    """Get snapshots for all watchlist symbols."""
    try:
        adapter = get_dxfeed_adapter()
        ticks = adapter.get_watchlist()
        return {
            "instruments": [t.to_dict() for t in ticks],
            "count": len(ticks),
        }
    except Exception as exc:
        logger.error("watchlist_error", error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/watchlist/add")
async def add_to_watchlist(req: WatchlistModifyRequest) -> Dict[str, Any]:
    """Add a symbol to the watchlist."""
    try:
        adapter = get_dxfeed_adapter()
        adapter.add_symbol(req.symbol)
        return {"success": True, "symbol": req.symbol, "watchlist_size": len(adapter.watchlist_symbols)}
    except Exception as exc:
        logger.error("watchlist_add_error", error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/watchlist/remove")
async def remove_from_watchlist(req: WatchlistModifyRequest) -> Dict[str, Any]:
    """Remove a symbol from the watchlist."""
    try:
        adapter = get_dxfeed_adapter()
        adapter.remove_symbol(req.symbol)
        return {"success": True, "symbol": req.symbol, "watchlist_size": len(adapter.watchlist_symbols)}
    except Exception as exc:
        logger.error("watchlist_remove_error", error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc))


# ── WebSocket streaming endpoint ─────────────────────────────────────
#
# Pairs with LightweightPriceChart.tsx on the frontend.
# When dxFeed credentials are available, this will forward real ticks.
# For now, it polls the adapter snapshot at a configurable interval.

ws_router = APIRouter(tags=["market-data-ws"])

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
        adapter = get_dxfeed_adapter()
        adapter.add_symbol(symbol)

        while True:
            try:
                tick = adapter.get_snapshot(symbol)
                candle = {
                    "time": int(time.time()),
                    "open": tick.bid or tick.last or 0,
                    "high": tick.ask or tick.last or 0,
                    "low": tick.bid or tick.last or 0,
                    "close": tick.last or tick.ask or 0,
                    "volume": getattr(tick, "volume_24h", None) or 0,
                }
                await websocket.send_text(json.dumps(candle))
            except Exception as exc:
                logger.warning("ws_market_tick_error", symbol=symbol, error=str(exc))

            await asyncio.sleep(_WS_POLL_INTERVAL_S)

    except WebSocketDisconnect:
        logger.info("ws_market_disconnect", symbol=symbol)
    except Exception as exc:
        logger.error("ws_market_error", symbol=symbol, error=str(exc))
        try:
            await websocket.close(code=1011, reason=str(exc))
        except Exception as exc:
            logger.debug("async_op_suppressed", error=str(exc))
