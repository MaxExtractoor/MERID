"""
Agent Mesh - Dedicated agent-to-agent communication layer.

This layer provides formal protocols for agent communication,
separate from the UI layer and event bus.

Key principles:
- Agents communicate through mesh, not UI
- Messages are typed and validated
- No dependency on user-facing services
- Supports both direct and broadcast messaging
"""

from __future__ import annotations

import time
import threading
from typing import Any, Dict, List, Optional, Callable
from dataclasses import dataclass, field
from enum import Enum
from collections import defaultdict

from utils.logger import get_logger

logger = get_logger("agent.mesh")


class MessageType(Enum):
    """Types of agent mesh messages."""
    SIGNAL = "signal"              # Simple signal between agents
    REQUEST = "request"            # Request for action/data
    RESPONSE = "response"          # Response to request
    BROADCAST = "broadcast"        # Broadcast to all agents
    CONSENSUS_VOTE = "consensus_vote"  # Vote in consensus round
    TASK_HANDOFF = "task_handoff"  # Transfer task to another agent
    STATUS_UPDATE = "status_update"  # Agent status change


@dataclass
class MeshMessage:
    """Message passed through agent mesh."""
    message_id: str
    message_type: MessageType
    from_agent: str
    to_agent: Optional[str]  # None for broadcasts
    payload: Dict[str, Any]
    timestamp: float = field(default_factory=time.time)
    correlation_id: Optional[str] = None  # For request/response pairing
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "message_id": self.message_id,
            "message_type": self.message_type.value,
            "from_agent": self.from_agent,
            "to_agent": self.to_agent,
            "payload": self.payload,
            "timestamp": self.timestamp,
            "correlation_id": self.correlation_id,
        }


class AgentMesh:
    """
    Dedicated agent-to-agent communication layer.
    
    Responsibilities:
    - Route messages between agents
    - Broadcast to all agents
    - Track agent availability
    - Message queuing and delivery
    - No UI dependency
    """
    
    def __init__(self):
        # Agent registry
        self._agents: Dict[str, Dict[str, Any]] = {}
        self._agent_lock = threading.RLock()
        
        # Message handlers
        self._handlers: Dict[str, List[Callable]] = defaultdict(list)
        self._handler_lock = threading.RLock()
        
        # Message queue (for async delivery)
        self._message_queue: List[MeshMessage] = []
        self._queue_lock = threading.Lock()
        
        # Stats
        self._messages_sent = 0
        self._messages_delivered = 0
        self._messages_dropped = 0
        self._start_time = time.time()
        
        logger.info("AgentMesh initialized")
    
    def register_agent(
        self,
        agent_id: str,
        agent_type: str,
        metadata: Optional[Dict[str, Any]] = None
    ):
        """
        Register an agent with the mesh.
        
        Args:
            agent_id: Unique agent identifier
            agent_type: Agent type/role
            metadata: Optional agent metadata
        """
        with self._agent_lock:
            self._agents[agent_id] = {
                "agent_id": agent_id,
                "agent_type": agent_type,
                "metadata": metadata or {},
                "registered_at": time.time(),
                "status": "active",
                "message_count": 0,
            }
        
        logger.info("Agent registered: %s (type: %s)", agent_id, agent_type)
    
    def unregister_agent(self, agent_id: str):
        """Unregister an agent from the mesh."""
        with self._agent_lock:
            if agent_id in self._agents:
                del self._agents[agent_id]
                logger.info("Agent unregistered: %s", agent_id)
    
    def register_handler(
        self,
        agent_id: str,
        message_type: MessageType,
        handler: Callable[[MeshMessage], None]
    ):
        """
        Register a message handler for an agent.
        
        Args:
            agent_id: Agent identifier
            message_type: Type of message to handle
            handler: Callback function
        """
        key = f"{agent_id}:{message_type.value}"
        
        with self._handler_lock:
            self._handlers[key].append(handler)
        
        logger.debug("Handler registered: %s for %s", agent_id, message_type.value)
    
    def send_message(
        self,
        from_agent: str,
        to_agent: str,
        message_type: MessageType,
        payload: Dict[str, Any],
        correlation_id: Optional[str] = None
    ) -> str:
        """
        Send a direct message to another agent.
        
        Args:
            from_agent: Sender agent ID
            to_agent: Recipient agent ID
            message_type: Type of message
            payload: Message payload
            correlation_id: Optional correlation ID for request/response
        
        Returns:
            message_id: Unique message identifier
        """
        # Validate agents exist
        with self._agent_lock:
            if from_agent not in self._agents:
                logger.warning("Unknown sender: %s", from_agent)
                self._messages_dropped += 1
                return ""
            
            if to_agent not in self._agents:
                logger.warning("Unknown recipient: %s", to_agent)
                self._messages_dropped += 1
                return ""
        
        # Create message
        message_id = f"msg-{int(time.time() * 1000)}-{self._messages_sent}"
        message = MeshMessage(
            message_id=message_id,
            message_type=message_type,
            from_agent=from_agent,
            to_agent=to_agent,
            payload=payload,
            correlation_id=correlation_id,
        )
        
        # Deliver message
        self._deliver_message(message)
        
        self._messages_sent += 1
        
        logger.debug(
            "Message sent: %s -> %s (%s)",
            from_agent, to_agent, message_type.value
        )
        
        return message_id
    
    def broadcast(
        self,
        from_agent: str,
        message_type: MessageType,
        payload: Dict[str, Any],
        exclude_self: bool = True
    ) -> int:
        """
        Broadcast a message to all agents.
        
        Args:
            from_agent: Sender agent ID
            message_type: Type of message
            payload: Message payload
            exclude_self: Whether to exclude sender from broadcast
        
        Returns:
            count: Number of agents message was sent to
        """
        with self._agent_lock:
            if from_agent not in self._agents:
                logger.warning("Unknown broadcaster: %s", from_agent)
                return 0
            
            # Get all agents except sender (if excluded)
            recipients = [
                agent_id for agent_id in self._agents.keys()
                if not (exclude_self and agent_id == from_agent)
            ]
        
        # Create broadcast message
        message_id = f"bcast-{int(time.time() * 1000)}-{self._messages_sent}"
        message = MeshMessage(
            message_id=message_id,
            message_type=message_type,
            from_agent=from_agent,
            to_agent=None,  # Broadcast
            payload=payload,
        )
        
        # Deliver to all recipients
        delivered = 0
        for recipient in recipients:
            message.to_agent = recipient
            self._deliver_message(message)
            delivered += 1
        
        self._messages_sent += delivered
        
        logger.debug(
            "Broadcast sent: %s -> %d agents (%s)",
            from_agent, delivered, message_type.value
        )
        
        return delivered
    
    def send_signal(
        self,
        from_agent: str,
        to_agent: str,
        signal: str,
        data: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Send a simple signal to another agent.
        
        Args:
            from_agent: Sender agent ID
            to_agent: Recipient agent ID
            signal: Signal name
            data: Optional signal data
        
        Returns:
            message_id: Unique message identifier
        """
        return self.send_message(
            from_agent=from_agent,
            to_agent=to_agent,
            message_type=MessageType.SIGNAL,
            payload={"signal": signal, "data": data or {}}
        )
    
    def request(
        self,
        from_agent: str,
        to_agent: str,
        request_type: str,
        params: Dict[str, Any]
    ) -> str:
        """
        Send a request to another agent.
        
        Args:
            from_agent: Sender agent ID
            to_agent: Recipient agent ID
            request_type: Type of request
            params: Request parameters
        
        Returns:
            correlation_id: ID for matching response
        """
        correlation_id = f"req-{int(time.time() * 1000)}"
        
        self.send_message(
            from_agent=from_agent,
            to_agent=to_agent,
            message_type=MessageType.REQUEST,
            payload={"request_type": request_type, "params": params},
            correlation_id=correlation_id
        )
        
        return correlation_id
    
    def respond(
        self,
        from_agent: str,
        to_agent: str,
        correlation_id: str,
        result: Dict[str, Any]
    ):
        """
        Send a response to a request.
        
        Args:
            from_agent: Sender agent ID
            to_agent: Recipient agent ID
            correlation_id: Correlation ID from original request
            result: Response result
        """
        self.send_message(
            from_agent=from_agent,
            to_agent=to_agent,
            message_type=MessageType.RESPONSE,
            payload={"result": result},
            correlation_id=correlation_id
        )
    
    def handoff_task(
        self,
        from_agent: str,
        to_agent: str,
        task: Dict[str, Any]
    ) -> str:
        """
        Hand off a task to another agent.
        
        Args:
            from_agent: Sender agent ID
            to_agent: Recipient agent ID
            task: Task details
        
        Returns:
            message_id: Unique message identifier
        """
        return self.send_message(
            from_agent=from_agent,
            to_agent=to_agent,
            message_type=MessageType.TASK_HANDOFF,
            payload={"task": task}
        )
    
    def _deliver_message(self, message: MeshMessage):
        """Deliver a message to its recipient."""
        if not message.to_agent:
            logger.warning("Cannot deliver message without recipient")
            self._messages_dropped += 1
            return
        
        # Find handlers
        key = f"{message.to_agent}:{message.message_type.value}"
        
        with self._handler_lock:
            handlers = self._handlers.get(key, [])
        
        if not handlers:
            logger.debug(
                "No handlers for %s message to %s",
                message.message_type.value, message.to_agent
            )
            # Still count as delivered (agent may not care)
            self._messages_delivered += 1
            return
        
        # Call handlers
        for handler in handlers:
            try:
                handler(message)
            except Exception as e:
                logger.error(
                    "Handler error for %s: %s",
                    message.to_agent, e, exc_info=True
                )
        
        # Update stats
        with self._agent_lock:
            if message.to_agent in self._agents:
                self._agents[message.to_agent]["message_count"] += 1
        
        self._messages_delivered += 1
    
    def get_agent_status(self, agent_id: str) -> Optional[Dict[str, Any]]:
        """Get status of an agent."""
        with self._agent_lock:
            return self._agents.get(agent_id)
    
    def get_all_agents(self) -> List[Dict[str, Any]]:
        """Get all registered agents."""
        with self._agent_lock:
            return list(self._agents.values())
    
    def get_stats(self) -> Dict[str, Any]:
        """Get mesh statistics."""
        uptime = time.time() - self._start_time
        
        with self._agent_lock:
            agent_count = len(self._agents)
            total_messages = sum(
                agent["message_count"] for agent in self._agents.values()
            )
        
        return {
            "agent_count": agent_count,
            "messages_sent": self._messages_sent,
            "messages_delivered": self._messages_delivered,
            "messages_dropped": self._messages_dropped,
            "total_agent_messages": total_messages,
            "uptime_seconds": round(uptime, 2),
            "messages_per_second": round(self._messages_sent / uptime, 2) if uptime > 0 else 0,
        }


# Global singleton
_agent_mesh: Optional[AgentMesh] = None


def get_agent_mesh() -> AgentMesh:
    """Get the global agent mesh instance."""
    global _agent_mesh
    if _agent_mesh is None:
        _agent_mesh = AgentMesh()
    return _agent_mesh


# FastAPI router for agent mesh endpoints
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/api/v1/mesh", tags=["agent_mesh"])


class RegisterAgentRequest(BaseModel):
    agent_id: str
    agent_type: str
    capabilities: List[str] = []


class SendMessageRequest(BaseModel):
    from_agent: str
    to_agent: Optional[str]
    message_type: str
    payload: Dict[str, Any]


@router.post("/register")
async def register_agent(request: RegisterAgentRequest):
    """Register an agent with the mesh."""
    mesh = get_agent_mesh()
    mesh.register_agent(request.agent_id)
    logger.info(f"Agent {request.agent_id} registered via API")
    return {"status": "registered", "agent_id": request.agent_id}


@router.post("/unregister")
async def unregister_agent(agent_id: str):
    """Unregister an agent from the mesh."""
    mesh = get_agent_mesh()
    mesh.unregister_agent(agent_id)
    logger.info(f"Agent {agent_id} unregistered via API")
    return {"status": "unregistered", "agent_id": agent_id}


@router.post("/message")
async def send_message(request: SendMessageRequest):
    """Send a message through the mesh."""
    mesh = get_agent_mesh()
    try:
        message_type = MessageType(request.message_type)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid message type: {request.message_type}")
    
    if request.to_agent:
        mesh.send_signal(request.from_agent, request.to_agent, request.payload)
    else:
        mesh.broadcast(request.from_agent, request.payload)
    
    return {"status": "sent", "from": request.from_agent, "to": request.to_agent or "broadcast"}


@router.get("/status")
async def mesh_status():
    """Get agent mesh status."""
    mesh = get_agent_mesh()
    return {
        "active_agents": len(mesh._agents),
        "total_messages": mesh._message_count,
        "agents": list(mesh._agents)
    }


@router.get("/agents")
async def list_agents():
    """List all registered agents."""
    mesh = get_agent_mesh()
    return {
        "agents": list(mesh._agents),
        "count": len(mesh._agents)
    }
