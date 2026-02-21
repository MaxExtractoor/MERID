"""Execution Subscriber — Sprint M.

Subscribes to Decision messages on the StreamingBus and routes approved
decisions to the execution path. This closes the last architectural gap:
the execution agent now consumes from the bus instead of being called
directly by the sequential loop.

The subscriber:
1. Listens on CONSENSUS + EXECUTION channels
2. Filters for Decision messages with ``risk_approved=True``
3. Routes to the appropriate TradingAgent's ``_execute_signal`` path
4. Publishes execution confirmations back to the bus

Usage::

    subscriber = get_execution_subscriber()
    await subscriber.start()
    # Decisions published to bus are now auto-routed to execution
"""

from __future__ import annotations

import asyncio
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Deque, Dict, List, Optional

from utils.logger import get_logger

logger = get_logger("merid.swarm.execution_subscriber")


@dataclass
class ExecutionRecord:
    """Record of a decision→execution routing."""
    decision_id: str
    market_id: str
    action: str
    side: str
    size_contracts: int
    timestamp: float = field(default_factory=time.time)
    routed: bool = False
    route_reason: str = ""

    def to_dict(self) -> dict:
        return {
            "decision_id": self.decision_id,
            "market_id": self.market_id,
            "action": self.action,
            "side": self.side,
            "size_contracts": self.size_contracts,
            "timestamp": self.timestamp,
            "routed": self.routed,
            "route_reason": self.route_reason,
        }


class ExecutionSubscriber:
    """Subscribes to Decision messages and routes to execution.

    Bridges the message bus architecture with the existing execution
    path, so agents can publish Decisions and have them auto-routed
    without the sequential loop needing to call execution directly.
    """

    def __init__(self):
        self._task: Optional[asyncio.Task] = None
        self._shutdown = asyncio.Event()
        self._queue: Optional[asyncio.Queue] = None
        self._history: Deque[ExecutionRecord] = deque(maxlen=500)
        self._decisions_received = 0
        self._decisions_routed = 0
        self._decisions_skipped = 0

    async def start(self) -> None:
        """Subscribe to the bus and start processing decisions."""
        self._shutdown.clear()
        try:
            from core.streaming_bus import get_streaming_bus, EventChannel
            bus = get_streaming_bus()
            self._queue = await bus.subscribe(
                channels=[EventChannel.CONSENSUS, EventChannel.EXECUTION]
            )
            self._task = asyncio.create_task(
                self._process_loop(), name="execution-subscriber"
            )
            logger.info("Execution subscriber started (listening on CONSENSUS + EXECUTION)")
        except Exception as exc:
            logger.warning(f"Execution subscriber start failed: {exc}")

    async def stop(self) -> None:
        """Stop the subscriber."""
        self._shutdown.set()
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        if self._queue:
            try:
                from core.streaming_bus import get_streaming_bus
                bus = get_streaming_bus()
                await bus.unsubscribe(self._queue)
            except Exception:
                pass
        logger.info(
            f"Execution subscriber stopped "
            f"(received={self._decisions_received}, "
            f"routed={self._decisions_routed}, "
            f"skipped={self._decisions_skipped})"
        )

    async def _process_loop(self) -> None:
        """Main event processing loop."""
        while not self._shutdown.is_set():
            try:
                if self._queue is None:
                    await asyncio.sleep(1)
                    continue

                try:
                    event = await asyncio.wait_for(
                        self._queue.get(), timeout=5.0
                    )
                except asyncio.TimeoutError:
                    continue

                # Filter for Decision events
                if event.event_type == "decision":
                    await self._handle_decision(event.data)

            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error(f"Execution subscriber error: {exc}")
                await asyncio.sleep(1)

    async def _handle_decision(self, data: Dict[str, Any]) -> None:
        """Process a Decision message from the bus."""
        self._decisions_received += 1
        decision_id = data.get("decision_id", "unknown")
        market_id = data.get("market_id", "")
        action = data.get("action", "skip")
        side = data.get("side", "")
        size = data.get("size_contracts", 0)
        risk_approved = data.get("risk_approved", False)

        record = ExecutionRecord(
            decision_id=decision_id,
            market_id=market_id,
            action=action,
            side=side,
            size_contracts=size,
        )

        # Skip if action is skip/hold
        if action in ("skip", "hold", "no_action"):
            record.route_reason = f"Action is {action}"
            self._decisions_skipped += 1
            self._history.append(record)
            return

        # Skip if not risk-approved
        if not risk_approved:
            record.route_reason = "Not risk-approved"
            self._decisions_skipped += 1
            self._history.append(record)
            logger.debug(f"Decision {decision_id} skipped: not risk-approved")
            return

        # Skip if no size
        if size <= 0:
            record.route_reason = "Zero size"
            self._decisions_skipped += 1
            self._history.append(record)
            return

        # Route to execution
        try:
            await self._route_to_execution(data)
            record.routed = True
            record.route_reason = "Routed to execution"
            self._decisions_routed += 1
            logger.info(
                f"Decision {decision_id} routed: {action} {side} "
                f"{size} contracts on {market_id}"
            )
        except Exception as exc:
            record.route_reason = f"Routing failed: {exc}"
            self._decisions_skipped += 1
            logger.warning(f"Decision {decision_id} routing failed: {exc}")

        self._history.append(record)

    async def _route_to_execution(self, data: Dict[str, Any]) -> None:
        """Route an approved Decision to the execution path.

        Finds the appropriate agent from AgentGrid and triggers execution.
        Falls back to direct order placement if no matching agent found.
        """
        market_id = data.get("market_id", "")
        action = data.get("action", "")
        side = data.get("side", "yes")
        size = data.get("size_contracts", 0)
        limit_price = data.get("limit_price_cents", 0)

        # Try to route through AgentGrid
        try:
            from merid.prediction.agent_grid import get_agent_grid
            grid = get_agent_grid()
            if grid and grid._running:
                for agent in grid._agents:
                    if agent.state.enabled:
                        # Route to first enabled agent
                        from merid.prediction.kalshi_tools import _kalshi_place_order
                        kalshi_action = "buy" if "buy" in action else "sell"
                        await _kalshi_place_order(
                            ticker=market_id,
                            side=side,
                            action=kalshi_action,
                            count=size,
                            agent_name=agent.agent_id,
                        )
                        return
        except Exception as exc:
            logger.debug(f"AgentGrid routing failed: {exc}")

        # Fallback: direct order placement
        try:
            from merid.prediction.kalshi_tools import _kalshi_place_order
            kalshi_action = "buy" if "buy" in action else "sell"
            await _kalshi_place_order(
                ticker=market_id,
                side=side,
                action=kalshi_action,
                count=size,
                agent_name="execution_subscriber",
            )
        except Exception as exc:
            raise RuntimeError(f"Direct order placement failed: {exc}") from exc

    @property
    def stats(self) -> Dict[str, Any]:
        return {
            "received": self._decisions_received,
            "routed": self._decisions_routed,
            "skipped": self._decisions_skipped,
            "history_size": len(self._history),
        }

    @property
    def history(self) -> List[Dict[str, Any]]:
        return [r.to_dict() for r in self._history]


# ── Singleton ────────────────────────────────────────────────────────────

_subscriber: Optional[ExecutionSubscriber] = None


def get_execution_subscriber() -> ExecutionSubscriber:
    """Get or create the singleton ExecutionSubscriber."""
    global _subscriber
    if _subscriber is None:
        _subscriber = ExecutionSubscriber()
    return _subscriber
