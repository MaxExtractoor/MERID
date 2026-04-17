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

from __future__ import annotations

# Lazy imports to avoid heavy dependency chains at import time
_imports_done = False
_exports = {}

def _ensure_imports():
    """Lazy import heavy modules on first access."""
    global _imports_done, _exports
    if _imports_done:
        return
    
    # Import lightweight modules first
    from core.events import EventEnvelope, EventType, create_audit_event
    from core.streaming_bus import streaming_bus, EventChannel
    from core.time_authority import current_time
    from core.energy import create_energy
    
    _exports.update({
        "EventEnvelope": EventEnvelope,
        "EventType": EventType,
        "create_audit_event": create_audit_event,
        "streaming_bus": streaming_bus,
        "EventChannel": EventChannel,
        "current_time": current_time,
        "create_energy": create_energy,
    })
    
    # Heavy modules (graph/orchestration) - import on demand
    from core.consensus_graph import ConsensusEngine, get_consensus_engine
    from core.agent_orchestrator import AgentOrchestrator, get_agent_orchestrator
    from core.intersystem_api import (
        InterSystemAPI, get_intersystem_api, Intent, IntentStatus,
        ExecutionConstraints, ExecutionReport, ProfitDeposit, RiskPreview,
        ShadowSimulation, PositionRequest, EmergencyFreeze, MeridSystem,
        ExecutionMode, FreezeReason, FreezeSeverity, APIError,
    )
    from core.system_orchestrator import (
        SystemOrchestrator, get_system_orchestrator, start_merid, stop_merid,
        OrchestratorState, SystemHealth, OrchestratorMetrics,
    )
    
    _exports.update({
        "ConsensusEngine": ConsensusEngine,
        "get_consensus_engine": get_consensus_engine,
        "AgentOrchestrator": AgentOrchestrator,
        "get_agent_orchestrator": get_agent_orchestrator,
        "InterSystemAPI": InterSystemAPI,
        "get_intersystem_api": get_intersystem_api,
        "Intent": Intent,
        "IntentStatus": IntentStatus,
        "ExecutionConstraints": ExecutionConstraints,
        "ExecutionReport": ExecutionReport,
        "ProfitDeposit": ProfitDeposit,
        "RiskPreview": RiskPreview,
        "ShadowSimulation": ShadowSimulation,
        "PositionRequest": PositionRequest,
        "EmergencyFreeze": EmergencyFreeze,
        "MeridSystem": MeridSystem,
        "ExecutionMode": ExecutionMode,
        "FreezeReason": FreezeReason,
        "FreezeSeverity": FreezeSeverity,
        "APIError": APIError,
        "SystemOrchestrator": SystemOrchestrator,
        "get_system_orchestrator": get_system_orchestrator,
        "start_merid": start_merid,
        "stop_merid": stop_merid,
        "OrchestratorState": OrchestratorState,
        "SystemHealth": SystemHealth,
        "OrchestratorMetrics": OrchestratorMetrics,
    })
    _imports_done = True

def __getattr__(name: str):
    """Lazy import on first attribute access."""
    if name.startswith("_"):
        raise AttributeError(f"module has no attribute '{name}'")
    
    _ensure_imports()
    if name in _exports:
        return _exports[name]
    raise AttributeError(f"cannot import '{name}' from 'core'")

def __dir__():
    """Return list of available exports."""
    return list(__all__)

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
