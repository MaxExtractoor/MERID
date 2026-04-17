"""Dashboard WebSocket hub — broadcasts real-time updates to connected clients."""
from __future__ import annotations

import asyncio
import json
from typing import Awaitable, Callable

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from data.live_price_feed import get_live_price_feed, PriceData
from utils.logger import get_logger

router = APIRouter()

logger = get_logger("web.api.dashboard_ws")
price_feed = get_live_price_feed()
_stream_task: asyncio.Task | None = None
_stream_lock = asyncio.Lock()


async def _ensure_price_stream() -> None:
    global _stream_task
    if _stream_task and not _stream_task.done():
        return
    async with _stream_lock:
        if _stream_task and not _stream_task.done():
            return
        logger.info("[WS] Starting live price streaming loop")
        _stream_task = asyncio.create_task(price_feed.start_streaming())


def _format_price_message(price: PriceData) -> dict:
    return {
        "type": "price_tick",
        "symbol": price.symbol,
        "price": price.price,
        "bid": price.bid,
        "ask": price.ask,
        "volume_24h": price.volume_24h,
        "change_24h": price.change_24h_pct,
        "timestamp": price.timestamp.isoformat(),
        "exchange": price.exchange,
    }


@router.websocket("/ws/dashboard-prices")
async def dashboard_prices_websocket(websocket: WebSocket):
    await websocket.accept()
    await _ensure_price_stream()
    queue: asyncio.Queue[dict] = asyncio.Queue(maxsize=500)

    async def handle_price(price_data: PriceData):
        message = _format_price_message(price_data)
        try:
            await queue.put(message)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # pragma: no cover - defensive
            logger.error("[WS] Failed to enqueue price update: %s", exc)

    price_feed.subscribe(handle_price)

    for cached_price in price_feed.get_all_prices().values():
        await websocket.send_text(json.dumps(_format_price_message(cached_price)))

    try:
        while True:
            message = await queue.get()
            await websocket.send_text(json.dumps(message))
    except WebSocketDisconnect:
        logger.info("[WS] Client disconnected")
    except Exception as exc:
        logger.error("[WS] Unexpected error: %s", exc)
    finally:
        price_feed.unsubscribe(handle_price)
