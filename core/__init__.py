"""
MERID Core Layer - Institutional-Grade System Foundation

Core infrastructure for consensus, events, orchestration, and state management.
"""

from core.events import EventEnvelope, EventType, create_audit_event
from core.consensus_graph import ConsensusEngine, get_consensus_engine
from core.agent_orchestrator import AgentOrchestrator, get_agent_orchestrator
from core.streaming_bus import streaming_bus, EventChannel
from core.time_authority import current_time
from core.energy import create_energy

__all__ = [
    "EventEnvelope",
    "EventType",
    "create_audit_event",
    "ConsensusEngine",
    "get_consensus_engine",
    "AgentOrchestrator",
    "get_agent_orchestrator",
    "streaming_bus",
    "EventChannel",
    "current_time",
    "create_energy",
]
