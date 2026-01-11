"""
Streaming Agent Base - Autonomous agent that subscribes to event streams.

This is the production agent architecture:
- Subscribes to event bus channels
- Runs continuous observe → analyze → vote loop
- Emits outputs autonomously
"""

from __future__ import annotations

import asyncio
import time
from typing import List, Optional, Dict, Any
from abc import ABC, abstractmethod

from core.streaming_bus import streaming_bus, EventChannel, StreamEvent, publish_agent_output
from utils.logger import get_logger


class StreamingAgent(ABC):
    """
    Base class for autonomous streaming agents.
    
    Agents subscribe to event channels and process events continuously.
    Each agent runs as an independent async task.
    """
    
    def __init__(
        self,
        agent_id: str,
        channels: List[EventChannel],
        model: str = "merid-strategist:latest"
    ):
        self.agent_id = agent_id
        self.channels = channels
        self.model = model
        self.logger = get_logger(f"agents.{agent_id}")
        
        # State
        self.running = False
        self.trust = 1.0
        self._task: Optional[asyncio.Task] = None
        self._queue: Optional[asyncio.Queue] = None
        
        # Metrics
        self.events_processed = 0
        self.outputs_emitted = 0
        self.errors = 0
        self.last_activity = time.time()
        self.avg_processing_time = 0.0
        
    async def start(self):
        """Start the agent's streaming loop."""
        if self.running:
            self.logger.warning(f"{self.agent_id} already running")
            return
        
        # Subscribe to event bus using agent_id as subscriber_id
        from core.streaming_bus import subscribe_by_id, _subscriber_queues
        await subscribe_by_id(self.agent_id, self.channels)
        self._queue = _subscriber_queues.get(self.agent_id)
        
        self.running = True
        self._task = asyncio.create_task(self._run_loop())
        
        self.logger.info(
            f"{self.agent_id} started - subscribed to {[c.value for c in self.channels]}"
        )
    
    async def stop(self):
        """Stop the agent's streaming loop."""
        self.running = False
        
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        
        # Unsubscribe using agent_id
        from core.streaming_bus import unsubscribe_by_id
        await unsubscribe_by_id(self.agent_id)
        
        self.logger.info(f"{self.agent_id} stopped")
    
    async def _run_loop(self):
        """Main agent loop: observe → analyze → vote."""
        self.logger.info(f"{self.agent_id} entering observe-analyze-vote loop")
        
        while self.running:
            try:
                # Observe: wait for event with timeout
                try:
                    event = await asyncio.wait_for(self._queue.get(), timeout=30.0)
                except asyncio.TimeoutError:
                    # No events, just continue
                    continue
                
                # Track timing
                start_time = time.time()
                self.last_activity = start_time
                
                # Analyze: process event with timeout
                try:
                    analysis = await asyncio.wait_for(self.analyze(event), timeout=10.0)
                except asyncio.TimeoutError:
                    self.logger.warning(f"{self.agent_id} analysis timed out")
                    self.errors += 1
                    continue
                
                if analysis:
                    # Vote/Output: emit result
                    await self.emit_output(analysis)
                    self.outputs_emitted += 1
                
                # Update metrics
                processing_time = time.time() - start_time
                self.avg_processing_time = (self.avg_processing_time * self.events_processed + processing_time) / (self.events_processed + 1)
                self.events_processed += 1
                
            except asyncio.CancelledError:
                self.logger.info(f"{self.agent_id} loop cancelled")
                break
            except Exception as exc:
                self.logger.error(f"{self.agent_id} error in loop: {exc}")
                self.errors += 1
                await asyncio.sleep(1)  # Back off on error
    
    @abstractmethod
    async def analyze(self, event: StreamEvent) -> Optional[Dict[str, Any]]:
        """
        Analyze an event and produce output.
        
        Args:
            event: Event from the stream
            
        Returns:
            Analysis result dict, or None if no output needed
        """
        pass
    
    async def emit_output(self, analysis: Dict[str, Any]):
        """Emit agent output to event bus."""
        await publish_agent_output(
            agent_id=self.agent_id,
            output_type=analysis.get("type", "analysis"),
            data=analysis
        )
        
        self.logger.debug(f"{self.agent_id} emitted output: {analysis.get('type')}")
    
    def get_metrics(self) -> Dict[str, Any]:
        """Get agent metrics."""
        return {
            "agent_id": self.agent_id,
            "running": self.running,
            "trust": self.trust,
            "model": self.model,
            "events_processed": self.events_processed,
            "outputs_emitted": self.outputs_emitted,
            "errors": self.errors,
            "avg_processing_time_ms": round(self.avg_processing_time * 1000, 2),
            "last_activity": self.last_activity,
            "uptime_seconds": time.time() - self.last_activity if self.last_activity else 0,
            "channels": [c.value for c in self.channels]
        }
