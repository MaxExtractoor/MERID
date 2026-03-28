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

# Lightweight sub-modules are imported eagerly; heavy sub-modules that pull in
# the agents/archivist/neo4j chain are deferred via PEP 562 __getattr__ so
# that importing `core.event_bus` (or any other lightweight submodule) does
# NOT trigger the full dependency graph.

from core.events import EventEnvelope, EventType, create_audit_event
from core.streaming_bus import streaming_bus, EventChannel
from core.time_authority import current_time
from core.energy import create_energy

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

_CONSENSUS_NAMES = frozenset({"ConsensusEngine", "get_consensus_engine"})
_ORCHESTRATOR_NAMES = frozenset({"AgentOrchestrator", "get_agent_orchestrator"})
_INTERSYSTEM_NAMES = frozenset({
    "InterSystemAPI", "get_intersystem_api", "Intent", "IntentStatus",
    "ExecutionConstraints", "ExecutionReport", "ProfitDeposit", "RiskPreview",
    "ShadowSimulation", "PositionRequest", "EmergencyFreeze", "MeridSystem",
    "ExecutionMode", "FreezeReason", "FreezeSeverity", "APIError",
})
_SYSTEM_ORCH_NAMES = frozenset({
    "SystemOrchestrator", "get_system_orchestrator", "start_merid", "stop_merid",
    "OrchestratorState", "SystemHealth", "OrchestratorMetrics",
})


def __getattr__(name: str):  # noqa: N807
    import sys as _sys
    _mod = _sys.modules[__name__]

    if name in _CONSENSUS_NAMES:
        from core.consensus_graph import ConsensusEngine, get_consensus_engine
        _mod.ConsensusEngine = ConsensusEngine
        _mod.get_consensus_engine = get_consensus_engine
        return _mod.__dict__[name]

    if name in _ORCHESTRATOR_NAMES:
        from core.agent_orchestrator import AgentOrchestrator, get_agent_orchestrator
        _mod.AgentOrchestrator = AgentOrchestrator
        _mod.get_agent_orchestrator = get_agent_orchestrator
        return _mod.__dict__[name]

    if name in _INTERSYSTEM_NAMES:
        from core.intersystem_api import (
            InterSystemAPI, get_intersystem_api, Intent, IntentStatus,
            ExecutionConstraints, ExecutionReport, ProfitDeposit, RiskPreview,
            ShadowSimulation, PositionRequest, EmergencyFreeze, MeridSystem,
            ExecutionMode, FreezeReason, FreezeSeverity, APIError,
        )
        for _k, _v in {
            "InterSystemAPI": InterSystemAPI, "get_intersystem_api": get_intersystem_api,
            "Intent": Intent, "IntentStatus": IntentStatus,
            "ExecutionConstraints": ExecutionConstraints, "ExecutionReport": ExecutionReport,
            "ProfitDeposit": ProfitDeposit, "RiskPreview": RiskPreview,
            "ShadowSimulation": ShadowSimulation, "PositionRequest": PositionRequest,
            "EmergencyFreeze": EmergencyFreeze, "MeridSystem": MeridSystem,
            "ExecutionMode": ExecutionMode, "FreezeReason": FreezeReason,
            "FreezeSeverity": FreezeSeverity, "APIError": APIError,
        }.items():
            setattr(_mod, _k, _v)
        return _mod.__dict__[name]

    if name in _SYSTEM_ORCH_NAMES:
        from core.system_orchestrator import (
            SystemOrchestrator, get_system_orchestrator, start_merid, stop_merid,
            OrchestratorState, SystemHealth, OrchestratorMetrics,
        )
        for _k, _v in {
            "SystemOrchestrator": SystemOrchestrator, "get_system_orchestrator": get_system_orchestrator,
            "start_merid": start_merid, "stop_merid": stop_merid,
            "OrchestratorState": OrchestratorState, "SystemHealth": SystemHealth,
            "OrchestratorMetrics": OrchestratorMetrics,
        }.items():
            setattr(_mod, _k, _v)
        return _mod.__dict__[name]

    raise AttributeError(f"module 'core' has no attribute {name!r}")
