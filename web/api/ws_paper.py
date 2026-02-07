"""WebSocket endpoints for live paper trading and agent telemetry."""

from __future__ import annotations

import asyncio
import time
from typing import Any, Callable, Dict, List

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from trading.paper_trading import get_paper_engine
from trading.mode_controller import get_trading_mode_controller
from core.agent_orchestrator import get_agent_orchestrator
from utils.logger import get_logger

router = APIRouter(prefix="/ws", tags=["ws-telemetry"])
logger = get_logger("web.api.ws_paper")

HEARTBEAT_INTERVAL = 10


async def _stream_subscription(
    websocket: WebSocket,
    subscribe_fn: Callable[[Callable[[Dict[str, Any]], None]], Callable[[], None]],
) -> None:
    await websocket.accept()
    queue: asyncio.Queue[Dict[str, Any]] = asyncio.Queue(maxsize=256)
    loop = asyncio.get_running_loop()

    def _listener(payload: Dict[str, Any]) -> None:
        try:
            loop.call_soon_threadsafe(queue.put_nowait, payload)
        except asyncio.QueueFull:
            logger.warning("Dropping telemetry payload (queue full): type=%s", payload.get("type"))

    unsubscribe = subscribe_fn(_listener)

    try:
        while True:
            try:
                payload = await asyncio.wait_for(queue.get(), timeout=HEARTBEAT_INTERVAL)
                await websocket.send_json(payload)
            except asyncio.TimeoutError:
                await websocket.send_json({"type": "heartbeat", "ts": time.time()})
    except WebSocketDisconnect:
        logger.info("Telemetry websocket disconnected")
    except Exception as exc:
        logger.error("Telemetry websocket error: %s", exc)
    finally:
        unsubscribe()


@router.websocket("/paper/summary")
async def paper_summary_stream(websocket: WebSocket) -> None:
    engine = get_paper_engine()
    await _stream_subscription(websocket, engine.subscribe_to_summary)


@router.websocket("/paper/trades")
async def paper_trades_stream(websocket: WebSocket, limit: int = 50) -> None:
    engine = get_paper_engine()
    await _stream_subscription(websocket, lambda cb: engine.subscribe_to_trades(cb, limit=limit))


@router.websocket("/paper/positions")
async def paper_positions_stream(websocket: WebSocket, limit: int = 50) -> None:
    engine = get_paper_engine()
    await _stream_subscription(websocket, lambda cb: engine.subscribe_to_positions(cb, limit=limit))


@router.websocket("/agents/activity")
async def agents_activity_stream(websocket: WebSocket) -> None:
    await websocket.accept()
    controller = get_trading_mode_controller()
    orchestrator = get_agent_orchestrator()
    prev_snapshot: List[Dict[str, Any]] = []

    try:
        while True:
            snapshot = _build_agent_snapshot(orchestrator)
            if snapshot != prev_snapshot:
                payload = {
                    "type": "agent_snapshot",
                    "agents": snapshot,
                    "mode": {
                        "name": controller.mode_name,
                        "is_paper": controller.is_paper,
                        "is_live": controller.is_live,
                        "is_autonomous": controller.is_autonomous,
                    },
                    "ts": time.time(),
                }
                await websocket.send_json(payload)
                prev_snapshot = snapshot
            else:
                await websocket.send_json({"type": "heartbeat", "ts": time.time()})
            await asyncio.sleep(5)
    except WebSocketDisconnect:
        logger.info("Agent activity websocket disconnected")
    except Exception as exc:
        logger.error("Agent activity websocket error: %s", exc)


def _build_agent_snapshot(orchestrator) -> List[Dict[str, Any]]:
    snapshot: List[Dict[str, Any]] = []
    agents = getattr(orchestrator, "agents", {})
    for role, agent in agents.items():
        agent_id = getattr(agent, "agent_id", getattr(role, "value", str(role)))
        role_name = getattr(role, "value", getattr(agent, "role", "agent"))
        status = "running" if getattr(agent, "enabled", True) else "offline"
        last_action = getattr(agent, "last_activity", None)
        model = getattr(agent, "model_name", getattr(agent, "model", "n/a"))
        snapshot.append(
            {
                "agent_id": agent_id,
                "role": role_name,
                "status": status,
                "model": model,
                "last_action_at": last_action,
            }
        )
    return snapshot
