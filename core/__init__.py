"""
MERID Core Layer - Institutional-Grade System Foundation

Core infrastructure for consensus, events, orchestration, and state management.

Layer 0 of Master Build Directive - CONSTITUTIONAL FOUNDATION

Components:
- Consensus Engine: Quorum + veto logic
- Event Bus: Inter-system communication
- System Orchestrator: Central nervous system
- Inter-System API: Authority-enforced contracts
"""

from core.events import EventEnvelope, EventType, create_audit_event
from core.consensus_graph import ConsensusEngine, get_consensus_engine
from core.agent_orchestrator import AgentOrchestrator, get_agent_orchestrator
from core.streaming_bus import streaming_bus, EventChannel
from core.time_authority import current_time
from core.energy import create_energy
from core.intersystem_api import (
    InterSystemAPI,
    get_intersystem_api,
    Intent,
    IntentStatus,
    ExecutionConstraints,
    ExecutionReport,
    ProfitDeposit,
    RiskPreview,
    ShadowSimulation,
    PositionRequest,
    EmergencyFreeze,
    MeridSystem,
    ExecutionMode,
    FreezeReason,
    FreezeSeverity,
    APIError,
)
from core.system_orchestrator import (
    SystemOrchestrator,
    get_system_orchestrator,
    start_merid,
    stop_merid,
    OrchestratorState,
    SystemHealth,
    OrchestratorMetrics,
)

__all__ = [
    # Events
    "EventEnvelope",
    "EventType",
    "create_audit_event",
    # Consensus
    "ConsensusEngine",
    "get_consensus_engine",
    # Agent Orchestration
    "AgentOrchestrator",
    "get_agent_orchestrator",
    # Streaming
    "streaming_bus",
    "EventChannel",
    # Time
    "current_time",
    "create_energy",
    # Inter-System API
    "InterSystemAPI",
    "get_intersystem_api",
    "Intent",
    "IntentStatus",
    "ExecutionConstraints",
    "ExecutionReport",
    "ProfitDeposit",
    "RiskPreview",
    "ShadowSimulation",
    "PositionRequest",
    "EmergencyFreeze",
    "MeridSystem",
    "ExecutionMode",
    "FreezeReason",
    "FreezeSeverity",
    "APIError",
    # System Orchestrator
    "SystemOrchestrator",
    "get_system_orchestrator",
    "start_merid",
    "stop_merid",
    "OrchestratorState",
    "SystemHealth",
    "OrchestratorMetrics",
]
