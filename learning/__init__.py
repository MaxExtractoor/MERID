"""
MERID Learning Module

Phase 5 of Master Build Directive - LEARNING & SWARM

WARNING: This module may only be used AFTER Phases 1-4 are operational.
Learning without perception is a fatal architectural error.

Components:
- MARL: Multi-Agent Reinforcement Learning (MAPPO, COMA, QMIX, VDN, IPPO)
- Meta-Learning: MAML, regime-conditioned policies
- Swarm Intelligence: PSO, ACO, ABC, Boids, DeepSwarm
"""

# MARL imports
from learning.marl import (
    MARLAgent,
    MARLPolicy,
    MARLCritic,
    MultiAgentEnvironment,
    Experience,
    Trajectory,
    MAPPO,
    MAPPOConfig,
    COMA,
    COMAConfig,
    QMIX,
    QMIXConfig,
    VDN,
    VDNConfig,
    IPPO,
    IPPOConfig,
    MARLCoordinator,
    get_marl_coordinator,
)

# Meta-Learning imports
from learning.meta import (
    MAML,
    MAMLConfig,
    MAMLTask,
    RegimeConditionedPolicy,
    RegimeConditionedConfig,
    RegimeAdapter,
    get_regime_adapter,
)

# Swarm Intelligence imports
from learning.swarm import (
    PSO,
    PSOConfig,
    Particle,
    ACO,
    ACOConfig,
    Ant,
    ABC,
    ABCConfig,
    Bee,
    Boids,
    BoidsConfig,
    Boid,
    DeepSwarm,
    DeepSwarmConfig,
    SwarmCoordinator,
    get_swarm_coordinator,
)

__all__ = [
    # MARL Base
    "MARLAgent",
    "MARLPolicy",
    "MARLCritic",
    "MultiAgentEnvironment",
    "Experience",
    "Trajectory",
    # MARL Algorithms
    "MAPPO",
    "MAPPOConfig",
    "COMA",
    "COMAConfig",
    "QMIX",
    "QMIXConfig",
    "VDN",
    "VDNConfig",
    "IPPO",
    "IPPOConfig",
    "MARLCoordinator",
    "get_marl_coordinator",
    # Meta-Learning
    "MAML",
    "MAMLConfig",
    "MAMLTask",
    "RegimeConditionedPolicy",
    "RegimeConditionedConfig",
    "RegimeAdapter",
    "get_regime_adapter",
    # Swarm Intelligence
    "PSO",
    "PSOConfig",
    "Particle",
    "ACO",
    "ACOConfig",
    "Ant",
    "ABC",
    "ABCConfig",
    "Bee",
    "Boids",
    "BoidsConfig",
    "Boid",
    "DeepSwarm",
    "DeepSwarmConfig",
    "SwarmCoordinator",
    "get_swarm_coordinator",
]
