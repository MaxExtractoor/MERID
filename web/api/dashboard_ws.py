"""Dashboard WebSocket hub — broadcasts real-time updates to connected clients."""
from __future__ import annotations

import asyncio
import json
from typing import Awaitable, Callable

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from data.unified_spot_service import get_unified_spot_service
from utils.logger import get_logger

router = APIRouter()

logger = get_logger("web.api.dashboard_ws")
_spot_service = None
_stream_task: asyncio.Task | None = None
_stream_lock = asyncio.Lock()


def _get_spot_service():
    """Lazy initialization of UnifiedSpotService."""
    global _spot_service
    if _spot_service is None:
        _spot_service = get_unified_spot_service()
    return _spot_service


async def _ensure_price_stream() -> None:
    global _stream_task
    if _stream_task and not _stream_task.done():
        return
    async with _stream_lock:
        if _stream_task and not _stream_task.done():
            return
        logger.info("[WS] Starting unified spot service streaming")
        service = _get_spot_service()
        if not service._running:
            await service.start_streaming()


def _format_price_message(asset: str, price_data: dict) -> dict:
    """Format price data from UnifiedSpotService for WebSocket message."""
    return {
        "type": "price_tick",
        "symbol": asset,
        "price": price_data.get("price"),
        "timestamp": price_data.get("timestamp"),
        "source": price_data.get("source"),
    }


@router.websocket("/ws/dashboard-prices")
async def dashboard_prices_websocket(websocket: WebSocket):
    await websocket.accept()
    await _ensure_price_stream()
    service = _get_spot_service()
    
    # Send initial cached prices
    all_prices = service.get_all()
    for asset, price_data in all_prices.items():
        if price_data:
            message = _format_price_message(asset, price_data)
            await websocket.send_text(json.dumps(message))
    
    # Poll for price updates every 1 second
    try:
        last_prices = {asset: data.get("price") if data else None for asset, data in all_prices.items()}
        while True:
            await asyncio.sleep(1)
            current_prices = service.get_all()
            for asset, price_data in current_prices.items():
                if price_data:
                    current_price = price_data.get("price")
                    if current_price != last_prices.get(asset):
                        message = _format_price_message(asset, price_data)
                        await websocket.send_text(json.dumps(message))
                        last_prices[asset] = current_price
    except WebSocketDisconnect:
        logger.info("[WS] Client disconnected")
    except Exception as exc:
        logger.error("[WS] Unexpected error: %s", exc)
