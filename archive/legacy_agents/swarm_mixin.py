"""
Swarm Agent Mixin - Adds swarm contract support to BaseAgent

Provides:
- StrategyOpinion emission for strategy agents
- AgentHeartbeat emission for all agents
- State version tracking
- Integration with SwarmTelemetry
"""

from __future__ import annotations

import asyncio
import hashlib
import time
from typing import Any, Dict, Optional

from schemas.swarm_events import (
    StrategyOpinion,
    OpinionDirection,
    AgentHeartbeat,
    TradingMode,
)
from observability.event_stream import publish_event
from observability.swarm_telemetry import get_swarm_telemetry
from utils.logger import get_logger

logger = get_logger("agents.swarm_mixin")


class SwarmAgentMixin:
    """
    Mixin for BaseAgent to add swarm contract support.
    
    Usage:
        class MyStrategyAgent(SwarmAgentMixin, BaseAgent):
            ...
    """
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        # Heartbeat tracking
        self._heartbeat_interval = 30.0  # seconds
        self._last_heartbeat = 0.0
        self._messages_processed = 0
        self._error_count = 0
        self._processing_latencies = []
        self._heartbeat_task: Optional[asyncio.Task] = None
        
        # Mode tracking
        self._current_mode = TradingMode.MOCK
    
    def set_trading_mode(self, mode: TradingMode) -> None:
        """Set current trading mode."""
        self._current_mode = mode
        logger.info(f"Agent {self.agent_id} mode set to {mode.value}")
    
    async def emit_strategy_opinion(
        self,
        symbol: str,
        direction: str,  # "long", "short", "flat", "reduce", "close"
        confidence: float,
        reasoning: str,
        venue: str = "binance",
        horizon: str = "1h",
        price: float = 0.0,
        signal_strength: float = 0.0,
        state_context: Optional[Dict[str, Any]] = None,
    ) -> StrategyOpinion:
        """
        Emit a strategy opinion event.
        
        This is the PRIMARY output for strategy agents - they should emit
        opinions, not create orders directly.
        """
        # Map string direction to OpinionDirection enum
        direction_map = {
            "long": OpinionDirection.LONG,
            "short": OpinionDirection.SHORT,
            "flat": OpinionDirection.FLAT,
            "reduce": OpinionDirection.REDUCE,
            "close": OpinionDirection.CLOSE,
            "bullish": OpinionDirection.LONG,
            "bearish": OpinionDirection.SHORT,
            "neutral": OpinionDirection.FLAT,
        }
        
        opinion_direction = direction_map.get(direction.lower(), OpinionDirection.FLAT)
        
        # Compute state version from context
        state_version = self._compute_state_version(state_context or {})
        
        # Create opinion
        opinion = StrategyOpinion(
            agent_id=self.agent_id,
            agent_role=getattr(self, "agent_role", "strategy").value if hasattr(getattr(self, "agent_role", "strategy"), "value") else "strategy",
            symbol=symbol,
            venue=venue,
            horizon=horizon,
            direction=opinion_direction,
            confidence=max(0.0, min(1.0, confidence)),  # Clamp 0-1
            rationale_summary=reasoning[:500],  # Truncate for display
            signal_strength=signal_strength,
            state_version=state_version,
            price_at_opinion=price,
        )
        
        # Publish to event stream
        await publish_event("strategy_opinion", opinion.to_dict())
        
        # Record in telemetry
        telemetry = get_swarm_telemetry()
        telemetry.record_opinion(opinion)
        
        logger.info(
            f"Opinion emitted: {self.agent_id} → {symbol} {opinion_direction.value} "
            f"(conf={confidence:.2f})"
        )
        
        return opinion
    
    async def emit_heartbeat(self) -> None:
        """Emit agent heartbeat for liveness monitoring."""
        now = time.time()
        
        # Calculate metrics
        avg_latency = (
            sum(self._processing_latencies) / len(self._processing_latencies)
            if self._processing_latencies else 0.0
        )
        
        p50_latency = avg_latency  # Simplified
        p99_latency = (
            max(self._processing_latencies) if self._processing_latencies else 0.0
        )
        
        # Create heartbeat
        heartbeat = AgentHeartbeat(
            agent_id=self.agent_id,
            agent_type=getattr(self, "agent_role", "unknown").value if hasattr(getattr(self, "agent_role", "unknown"), "value") else "unknown",
            status="healthy" if self._error_count < 10 else "degraded",
            messages_processed_count=self._messages_processed,
            error_count=self._error_count,
            processing_latency_p50_ms=p50_latency,
            processing_latency_p99_ms=p99_latency,
            current_mode=self._current_mode,
        )
        
        # Publish to event stream
        await publish_event("agent_heartbeat", heartbeat.to_dict())
        
        # Record in telemetry
        telemetry = get_swarm_telemetry()
        telemetry.record_heartbeat(heartbeat)
        
        self._last_heartbeat = now
    
    async def start_heartbeat_loop(self) -> None:
        """Start periodic heartbeat emission."""
        if self._heartbeat_task is not None:
            logger.warning(f"Heartbeat loop already running for {self.agent_id}")
            return
        
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
        logger.info(f"Heartbeat loop started for {self.agent_id}")
    
    async def stop_heartbeat_loop(self) -> None:
        """Stop heartbeat emission."""
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass
            self._heartbeat_task = None
            logger.info(f"Heartbeat loop stopped for {self.agent_id}")
    
    async def _heartbeat_loop(self) -> None:
        """Background loop for heartbeat emission."""
        while True:
            try:
                await self.emit_heartbeat()
                await asyncio.sleep(self._heartbeat_interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Heartbeat error for {self.agent_id}: {e}")
                await asyncio.sleep(self._heartbeat_interval)
    
    def _compute_state_version(self, state_context: Dict[str, Any]) -> str:
        """
        Compute deterministic hash of market state.
        
        Used to detect if agent is trading on stale data.
        """
        # Extract key state components
        components = {
            "timestamp": state_context.get("timestamp", time.time()),
            "price": state_context.get("price", 0.0),
            "symbol": state_context.get("symbol", ""),
        }
        
        # T-068: Upgrade from MD5 to SHA-256 and include nonce for replay protection
        import uuid as _uuid
        nonce = _uuid.uuid4().hex[:8]
        state_str = f"{components['timestamp']:.0f}_{components['symbol']}_{components['price']:.2f}_{nonce}"
        return hashlib.sha256(state_str.encode()).hexdigest()
    
    def _track_processing(self, latency_ms: float, error: bool = False) -> None:
        """Track processing metrics for heartbeat."""
        self._messages_processed += 1
        if error:
            self._error_count += 1
        
        self._processing_latencies.append(latency_ms)
        # Keep only recent 100 samples
        if len(self._processing_latencies) > 100:
            self._processing_latencies.pop(0)


def adapt_base_agent_vote_to_opinion(
    agent_id: str,
    symbol: str,
    vote: str,
    confidence: float,
    reasoning: str,
    price: float = 0.0,
) -> Dict[str, Any]:
    """
    Helper to convert legacy BaseAgent vote format to StrategyOpinion.
    
    Use this during transition period before all agents are updated.
    """
    # Map vote strings to directions
    vote_to_direction = {
        "approve": "long",
        "bullish": "long",
        "buy": "long",
        "reject": "short",
        "bearish": "short",
        "sell": "short",
        "abstain": "flat",
        "neutral": "flat",
        "hold": "flat",
    }
    
    direction = vote_to_direction.get(vote.lower(), "flat")
    
    return {
        "agent_id": agent_id,
        "symbol": symbol,
        "direction": direction,
        "confidence": confidence,
        "reasoning": reasoning,
        "price": price,
    }
