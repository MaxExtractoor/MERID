"""
MERID Learning - Multi-Agent Reinforcement Learning (MARL) Core

Phase 5.1 of Master Build Directive

Implements:
- MAPPO (Multi-Agent PPO)
- COMA (Counterfactual Multi-Agent Policy Gradients)
- QMIX (Monotonic Value Function Factorization)
- VDN (Value Decomposition Networks)
- IPPO (Independent PPO)

WARNING: This module may only be used AFTER Phases 1-4 are operational.
Learning without perception is a fatal architectural error.
"""

from learning.marl.base import (
    MARLAgent,
    MARLPolicy,
    MARLCritic,
    MultiAgentEnvironment,
    Experience,
    Trajectory,
)
from learning.marl.mappo import MAPPO, MAPPOConfig
from learning.marl.coma import COMA, COMAConfig
from learning.marl.qmix import QMIX, QMIXConfig
from learning.marl.vdn import VDN, VDNConfig
from learning.marl.ippo import IPPO, IPPOConfig
from learning.marl.coordinator import MARLCoordinator, get_marl_coordinator

__all__ = [
    # Base
    "MARLAgent",
    "MARLPolicy",
    "MARLCritic",
    "MultiAgentEnvironment",
    "Experience",
    "Trajectory",
    # Algorithms
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
    # Coordinator
    "MARLCoordinator",
    "get_marl_coordinator",
]
