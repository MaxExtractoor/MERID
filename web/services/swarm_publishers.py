"""
WebSocket Publishers for Swarm Events

Publishes swarm events to connected WebSocket clients:
- strategy_opinion
- consensus_decision  
- trade_intent
- order_event
- agent_heartbeat
- watchdog_alert
- swarm_telemetry
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict

from observability.event_stream import get_event_stream, EventRecord
from observability.swarm_telemetry import get_swarm_telemetry
from agents.watchdog_agents import get_watchdog_coordinator
from utils.logger import get_logger

logger = get_logger("web.swarm_publishers")


class SwarmEventPublisher:
    """Publishes swarm events to WebSocket clients."""
    
    def __init__(self):
        self._running = False
        self._tasks = []
        self.event_stream = get_event_stream()
        
    async def start(self) -> None:
        """Start all swarm publishers."""
        if self._running:
            logger.warning("SwarmEventPublisher already running")
            return
        
        self._running = True
        
        # Start event stream subscriber
        self._tasks.append(asyncio.create_task(self._event_subscriber()))
        
        # Start periodic telemetry publisher
        self._tasks.append(asyncio.create_task(self._telemetry_publisher()))
        
        logger.info("SwarmEventPublisher started")
    
    async def stop(self) -> None:
        """Stop all publishers."""
        self._running = False
        
        for task in self._tasks:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        
        self._tasks.clear()
        logger.info("SwarmEventPublisher stopped")
    
    async def _event_subscriber(self) -> None:
        """Subscribe to event stream and forward to WebSocket."""
        queue = await self.event_stream.subscribe()
        
        try:
            while self._running:
                try:
                    # Get event from queue with timeout
                    event: EventRecord = await asyncio.wait_for(
                        queue.get(),
                        timeout=1.0
                    )
                    
                    # Forward specific event types to WebSocket
                    if event.event_type in [
                        "strategy_opinion",
                        "consensus_decision",
                        "trade_intent",
                        "order_event",
                        "agent_heartbeat",
                        "watchdog_alert",
                    ]:
                        await self._broadcast_to_websocket(
                            event.event_type,
                            event.payload
                        )
                    
                except asyncio.TimeoutError:
                    continue
                except Exception as e:
                    logger.error(f"Event subscriber error: {e}")
                    await asyncio.sleep(1.0)
        
        finally:
            await self.event_stream.unsubscribe(queue)
    
    async def _telemetry_publisher(self) -> None:
        """Periodically publish swarm telemetry stats."""
        telemetry = get_swarm_telemetry()
        
        while self._running:
            try:
                # Get current stats
                stats = telemetry.get_stats_dict()
                
                # Broadcast to WebSocket
                await self._broadcast_to_websocket("swarm_telemetry", stats)
                
                # Wait 5 seconds before next update
                await asyncio.sleep(5.0)
                
            except Exception as e:
                logger.error(f"Telemetry publisher error: {e}")
                await asyncio.sleep(5.0)
    
    async def _broadcast_to_websocket(
        self,
        event_type: str,
        payload: Dict[str, Any]
    ) -> None:
        """Broadcast event to all WebSocket clients."""
        try:
            # Import here to avoid circular dependency
            from web.api.ws_events import broadcast_event
            
            await broadcast_event(event_type, payload)
            
        except ImportError:
            # WebSocket module not available yet
            pass
        except Exception as e:
            logger.debug(f"WebSocket broadcast error: {e}")


# Global instance
_swarm_publisher: SwarmEventPublisher | None = None


def get_swarm_publisher() -> SwarmEventPublisher:
    """Get or create global swarm publisher."""
    global _swarm_publisher
    if _swarm_publisher is None:
        _swarm_publisher = SwarmEventPublisher()
    return _swarm_publisher


async def start_swarm_publishers() -> None:
    """Start all swarm event publishers."""
    publisher = get_swarm_publisher()
    await publisher.start()
    logger.info("Swarm publishers started")


async def stop_swarm_publishers() -> None:
    """Stop all swarm event publishers."""
    publisher = get_swarm_publisher()
    await publisher.stop()
    logger.info("Swarm publishers stopped")
