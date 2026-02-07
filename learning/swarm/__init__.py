"""
MERID Learning - Swarm Intelligence

Phase 5.3 of Master Build Directive

Implements:
- PSO (Particle Swarm Optimization)
- ACO (Ant Colony Optimization)
- ABC (Artificial Bee Colony)
- Boids (Flocking behavior)
- DeepSwarm (Neural architecture search)

WARNING: This module may only be used AFTER Phases 1-4 are operational.
Swarm intelligence without perception is a fatal architectural error.
"""

from learning.swarm.pso import PSO, PSOConfig, Particle
from learning.swarm.aco import ACO, ACOConfig, Ant
from learning.swarm.abc import ABC, ABCConfig, Bee
from learning.swarm.boids import Boids, BoidsConfig, Boid
from learning.swarm.deep_swarm import DeepSwarm, DeepSwarmConfig
from learning.swarm.coordinator import SwarmCoordinator, get_swarm_coordinator

__all__ = [
    # PSO
    "PSO",
    "PSOConfig",
    "Particle",
    # ACO
    "ACO",
    "ACOConfig",
    "Ant",
    # ABC
    "ABC",
    "ABCConfig",
    "Bee",
    # Boids
    "Boids",
    "BoidsConfig",
    "Boid",
    # DeepSwarm
    "DeepSwarm",
    "DeepSwarmConfig",
    # Coordinator
    "SwarmCoordinator",
    "get_swarm_coordinator",
]
