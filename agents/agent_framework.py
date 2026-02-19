"""
Multi-Agent Framework for MERID
Agent registry, messaging, tools, and lifecycle management.
"""
from __future__ import annotations

import asyncio
import collections
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set

from core.environment import EnvironmentFlags, get_environment_flags
from core.network_client import RoutingProfile, get_network_client
from utils.logger import get_logger

logger = get_logger("agents.framework")


class AgentRole(Enum):
    """Agent roles in the swarm."""
    RESEARCH_SIGNAL = "research_signal"
    RISK = "risk"
    EXECUTION = "execution"
    ROUTING = "routing"
    ANOMALY_DETECTION = "anomaly_detection"
    GOVERNANCE = "governance"
    SNIPER_ARBITRAGE = "sniper_arbitrage"
    DEFI = "defi"
    MEMECOIN = "memecoin"
    XSTOCKS = "xstocks"
    WALLET_REBALANCING = "wallet_rebalancing"


class AgentStatus(Enum):
    """Agent status."""
    INITIALIZING = "initializing"
    ACTIVE = "active"
    PAUSED = "paused"
    DEGRADED = "degraded"
    STOPPED = "stopped"
    ERROR = "error"


class MessageType(Enum):
    """Message types for agent communication."""
    REQUEST = "request"
    RESPONSE = "response"
    BROADCAST = "broadcast"
    SIGNAL = "signal"
    COMMAND = "command"


@dataclass
class AgentMessage:
    """Message between agents."""
    message_id: str
    sender_id: str
    receiver_id: Optional[str]  # None for broadcast
    message_type: MessageType
    content: Dict[str, Any]
    timestamp: float
    correlation_id: Optional[str] = None


@dataclass
class AgentCapability:
    """Agent capability definition."""
    name: str
    description: str
    input_schema: Dict[str, Any]
    output_schema: Dict[str, Any]


@dataclass
class AgentMetrics:
    """Agent performance metrics."""
    agent_id: str
    messages_sent: int
    messages_received: int
    decisions_made: int
    success_rate: float
    average_latency_ms: float
    p95_latency_ms: float
    errors: int
    uptime_seconds: float


class Agent(ABC):
    """Base class for all agents."""
    
    def __init__(
        self,
        agent_id: str,
        role: AgentRole,
        capabilities: List[AgentCapability]
    ):
        self.agent_id = agent_id
        self.role = role
        self.capabilities = capabilities
        self.status = AgentStatus.INITIALIZING
        
        self._start_time = time.time()
        self._messages_sent = 0
        self._messages_received = 0
        self._decisions_made = 0
        self._errors = 0
        self._latency_samples: collections.deque = collections.deque(maxlen=200)
        self._message_queue: asyncio.Queue = asyncio.Queue()
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._env_flags: EnvironmentFlags = get_environment_flags()
        self._network_client = get_network_client()
    
    @abstractmethod
    async def process_message(self, message: AgentMessage) -> Optional[AgentMessage]:
        """Process an incoming message."""
        pass
    
    @abstractmethod
    async def make_decision(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Make a decision based on context."""
        pass
    
    async def start(self) -> None:
        """Start the agent."""
        if self._running:
            logger.warning(f"Agent {self.agent_id} already running")
            return
        
        self._running = True
        self.status = AgentStatus.ACTIVE
        self._task = asyncio.create_task(self._run_loop())
        
        logger.info(f"Started agent {self.agent_id} ({self.role.value})")
    
    async def stop(self) -> None:
        """Stop the agent."""
        self._running = False
        self.status = AgentStatus.STOPPED
        
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        
        logger.info(f"Stopped agent {self.agent_id}")
    
    async def pause(self) -> None:
        """Pause the agent."""
        self.status = AgentStatus.PAUSED
        logger.info(f"Paused agent {self.agent_id}")
    
    async def resume(self) -> None:
        """Resume the agent."""
        self.status = AgentStatus.ACTIVE
        logger.info(f"Resumed agent {self.agent_id}")
    
    async def send_message(self, message: AgentMessage) -> None:
        """Send a message to another agent."""
        from agents.agent_framework import get_agent_registry
        
        registry = get_agent_registry()
        await registry.route_message(message)
        
        self._messages_sent += 1
    
    async def receive_message(self, message: AgentMessage) -> None:
        """Receive a message."""
        await self._message_queue.put(message)
        self._messages_received += 1
    
    async def _run_loop(self) -> None:
        """Main agent loop."""
        while self._running:
            try:
                self._env_flags = get_environment_flags()
                if self.status == AgentStatus.PAUSED:
                    await asyncio.sleep(1.0)
                    continue
                
                # Process messages
                try:
                    message = await asyncio.wait_for(
                        self._message_queue.get(),
                        timeout=1.0
                    )
                    
                    t0 = time.monotonic()
                    response = await self.process_message(message)
                    self._latency_samples.append((time.monotonic() - t0) * 1000)
                    
                    if response:
                        await self.send_message(response)
                    
                except asyncio.TimeoutError:
                    pass
                
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error(f"Error in agent {self.agent_id} loop: {exc}")
                self._errors += 1
                self.status = AgentStatus.ERROR
                await asyncio.sleep(5.0)
    
    def record_latency(self, latency_ms: float) -> None:
        """Record a latency sample (ms) from an external caller (e.g. orchestrator)."""
        self._latency_samples.append(latency_ms)

    def get_metrics(self) -> AgentMetrics:
        """Get agent metrics."""
        samples = list(self._latency_samples)
        if samples:
            avg_lat = sum(samples) / len(samples)
            sorted_s = sorted(samples)
            p95_idx = min(int(len(sorted_s) * 0.95), len(sorted_s) - 1)
            p95_lat = sorted_s[p95_idx]
        else:
            avg_lat = 0.0
            p95_lat = 0.0
        return AgentMetrics(
            agent_id=self.agent_id,
            messages_sent=self._messages_sent,
            messages_received=self._messages_received,
            decisions_made=self._decisions_made,
            success_rate=1.0 - (self._errors / max(self._decisions_made, 1)),
            average_latency_ms=round(avg_lat, 2),
            p95_latency_ms=round(p95_lat, 2),
            errors=self._errors,
            uptime_seconds=time.time() - self._start_time
        )


class AgentRegistry:
    """Registry for managing agents."""
    
    def __init__(self):
        self._agents: Dict[str, Agent] = {}
        self._agents_by_role: Dict[AgentRole, List[Agent]] = {}
        self._message_counter = 0
    
    def register(self, agent: Agent) -> None:
        """Register an agent."""
        if agent.agent_id in self._agents:
            logger.warning(f"Agent {agent.agent_id} already registered, replacing")
        
        self._agents[agent.agent_id] = agent
        
        if agent.role not in self._agents_by_role:
            self._agents_by_role[agent.role] = []
        
        self._agents_by_role[agent.role].append(agent)
        
        logger.info(f"Registered agent {agent.agent_id} ({agent.role.value})")
    
    def unregister(self, agent_id: str) -> None:
        """Unregister an agent."""
        if agent_id not in self._agents:
            return
        
        agent = self._agents[agent_id]
        
        del self._agents[agent_id]
        
        if agent.role in self._agents_by_role:
            self._agents_by_role[agent.role] = [
                a for a in self._agents_by_role[agent.role]
                if a.agent_id != agent_id
            ]
        
        logger.info(f"Unregistered agent {agent_id}")
    
    def get_agent(self, agent_id: str) -> Optional[Agent]:
        """Get an agent by ID."""
        return self._agents.get(agent_id)
    
    def get_agents_by_role(self, role: AgentRole) -> List[Agent]:
        """Get all agents with a specific role."""
        return self._agents_by_role.get(role, [])
    
    def get_all_agents(self) -> List[Agent]:
        """Get all registered agents."""
        return list(self._agents.values())
    
    async def route_message(self, message: AgentMessage) -> None:
        """Route a message to the appropriate agent(s)."""
        if message.receiver_id:
            # Direct message
            agent = self._agents.get(message.receiver_id)
            if agent:
                await agent.receive_message(message)
            else:
                logger.warning(f"Agent {message.receiver_id} not found for message routing")
        else:
            # Broadcast message
            for agent in self._agents.values():
                if agent.agent_id != message.sender_id:
                    await agent.receive_message(message)
    
    async def start_all(self) -> None:
        """Start all registered agents."""
        for agent in self._agents.values():
            await agent.start()
        
        logger.info(f"Started {len(self._agents)} agents")
    
    async def stop_all(self) -> None:
        """Stop all registered agents."""
        for agent in self._agents.values():
            await agent.stop()
        
        logger.info("Stopped all agents")
    
    def get_all_metrics(self) -> Dict[str, AgentMetrics]:
        """Get metrics for all agents."""
        return {
            agent_id: agent.get_metrics()
            for agent_id, agent in self._agents.items()
        }
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get registry statistics."""
        return {
            "total_agents": len(self._agents),
            "agents_by_role": {
                role.value: len(agents)
                for role, agents in self._agents_by_role.items()
            },
            "agents_by_status": {
                status.value: sum(1 for a in self._agents.values() if a.status == status)
                for status in AgentStatus
            }
        }


class MessageBus:
    """Message bus for agent communication."""
    
    def __init__(self):
        self._subscribers: Dict[MessageType, List[Callable]] = {}
        self._message_history: List[AgentMessage] = []
        self._max_history = 1000
    
    def subscribe(
        self,
        message_type: MessageType,
        callback: Callable[[AgentMessage], None]
    ) -> None:
        """Subscribe to a message type."""
        if message_type not in self._subscribers:
            self._subscribers[message_type] = []
        
        self._subscribers[message_type].append(callback)
    
    async def publish(self, message: AgentMessage) -> None:
        """Publish a message."""
        self._message_history.append(message)
        
        if len(self._message_history) > self._max_history:
            self._message_history = self._message_history[-self._max_history:]
        
        if message.message_type in self._subscribers:
            for callback in self._subscribers[message.message_type]:
                try:
                    await callback(message)
                except Exception as exc:
                    logger.error(f"Error in message subscriber: {exc}")
    
    def get_history(
        self,
        message_type: Optional[MessageType] = None,
        sender_id: Optional[str] = None,
        limit: int = 100
    ) -> List[AgentMessage]:
        """Get message history."""
        messages = self._message_history
        
        if message_type:
            messages = [m for m in messages if m.message_type == message_type]
        if sender_id:
            messages = [m for m in messages if m.sender_id == sender_id]
        
        return messages[-limit:]


# Global instances
_agent_registry: Optional[AgentRegistry] = None
_message_bus: Optional[MessageBus] = None


def get_agent_registry() -> AgentRegistry:
    """Get the global agent registry."""
    global _agent_registry
    if _agent_registry is None:
        _agent_registry = AgentRegistry()
    return _agent_registry


def get_message_bus() -> MessageBus:
    """Get the global message bus."""
    global _message_bus
    if _message_bus is None:
        _message_bus = MessageBus()
    return _message_bus
