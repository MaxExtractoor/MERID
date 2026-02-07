"""
Simulation layer for MERID.

Provides shadow execution, parallel simulation, divergence detection,
attack simulation, and the ShadowGuardian agent.
"""

from simulation.shadow_merid import (
    ShadowMERID,
    ShadowConfig,
    ShadowMode,
    ShadowPortfolio,
    ShadowPosition,
    ShadowExecution,
    get_shadow_merid,
    start_shadow_merid,
    stop_shadow_merid,
)

from simulation.divergence_engine import (
    DivergenceEngine,
    DivergenceLevel,
    DivergenceMetric,
    DivergenceResult,
    DivergenceWeights,
    DivergenceThresholds,
    LiveState,
    ShadowState,
    get_divergence_engine,
)

from simulation.shadow_guardian import (
    ShadowGuardian,
    GuardianState,
    ThreatLevel,
    ThreatAssessment,
    ReplayConfig,
    ReplayResult,
    get_shadow_guardian,
    start_shadow_guardian,
    stop_shadow_guardian,
)

from simulation.attack_simulator import (
    AttackSimulator,
    AttackType,
    AttackSeverity,
    AttackConfig,
    AttackResult,
    get_attack_simulator,
)

__all__ = [
    "ShadowMERID",
    "ShadowConfig",
    "ShadowMode",
    "ShadowPortfolio",
    "ShadowPosition",
    "ShadowExecution",
    "get_shadow_merid",
    "start_shadow_merid",
    "stop_shadow_merid",
    "DivergenceEngine",
    "DivergenceLevel",
    "DivergenceMetric",
    "DivergenceResult",
    "DivergenceWeights",
    "DivergenceThresholds",
    "LiveState",
    "ShadowState",
    "get_divergence_engine",
    "ShadowGuardian",
    "GuardianState",
    "ThreatLevel",
    "ThreatAssessment",
    "ReplayConfig",
    "ReplayResult",
    "get_shadow_guardian",
    "start_shadow_guardian",
    "stop_shadow_guardian",
    "AttackSimulator",
    "AttackType",
    "AttackSeverity",
    "AttackConfig",
    "AttackResult",
    "get_attack_simulator",
]
