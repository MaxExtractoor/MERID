"""
MERID Swarm Intelligence Coordinator

Coordinates multiple swarm algorithms and manages optimization.
Integrates with MERID-OPS for problem awareness and MERID-GOV for approval.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple
import numpy as np

from learning.swarm.pso import PSO, PSOConfig
from learning.swarm.aco import ACO, ACOConfig
from learning.swarm.abc import ABC, ABCConfig
from learning.swarm.boids import Boids, BoidsConfig
from learning.swarm.deep_swarm import DeepSwarm, DeepSwarmConfig
from utils.logger import get_logger

logger = get_logger("learning.swarm.coordinator")


class SwarmAlgorithm(Enum):
    """Available swarm algorithms."""
    PSO = "pso"
    ACO = "aco"
    ABC = "abc"
    BOIDS = "boids"
    DEEP_SWARM = "deep_swarm"


@dataclass
class OptimizationResult:
    """Result of a swarm optimization."""
    algorithm: str
    best_solution: Any
    best_fitness: float
    n_iterations: int
    elapsed_seconds: float
    
    # History
    fitness_history: List[float] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "algorithm": self.algorithm,
            "best_fitness": round(self.best_fitness, 6) if self.best_fitness != float('-inf') else None,
            "n_iterations": self.n_iterations,
            "elapsed_seconds": round(self.elapsed_seconds, 2),
        }


class SwarmCoordinator:
    """
    Coordinates swarm intelligence algorithms.
    
    Responsibilities:
    - Algorithm selection and initialization
    - Optimization management
    - Integration with MERID systems
    - Performance tracking
    """
    
    def __init__(self):
        self._active_algorithm: Optional[Any] = None
        self._algorithm_type: Optional[SwarmAlgorithm] = None
        
        # Results
        self._optimization_results: List[OptimizationResult] = []
        
        logger.info("Swarm Coordinator initialized")
    
    def initialize_pso(
        self,
        n_particles: int = 30,
        n_dimensions: int = 10,
        config: Optional[PSOConfig] = None,
    ) -> PSO:
        """Initialize PSO algorithm."""
        if config is None:
            config = PSOConfig(n_particles=n_particles, n_dimensions=n_dimensions)
        
        self._active_algorithm = PSO(config)
        self._algorithm_type = SwarmAlgorithm.PSO
        
        logger.info("PSO initialized: %d particles, %d dimensions", n_particles, n_dimensions)
        return self._active_algorithm
    
    def initialize_aco(
        self,
        n_ants: int = 20,
        n_nodes: int = 10,
        config: Optional[ACOConfig] = None,
    ) -> ACO:
        """Initialize ACO algorithm."""
        if config is None:
            config = ACOConfig(n_ants=n_ants, n_nodes=n_nodes)
        
        self._active_algorithm = ACO(config)
        self._algorithm_type = SwarmAlgorithm.ACO
        
        logger.info("ACO initialized: %d ants, %d nodes", n_ants, n_nodes)
        return self._active_algorithm
    
    def initialize_abc(
        self,
        n_employed: int = 20,
        n_dimensions: int = 10,
        config: Optional[ABCConfig] = None,
    ) -> ABC:
        """Initialize ABC algorithm."""
        if config is None:
            config = ABCConfig(n_employed=n_employed, n_dimensions=n_dimensions)
        
        self._active_algorithm = ABC(config)
        self._algorithm_type = SwarmAlgorithm.ABC
        
        logger.info("ABC initialized: %d employed bees, %d dimensions", n_employed, n_dimensions)
        return self._active_algorithm
    
    def initialize_boids(
        self,
        n_boids: int = 30,
        n_dimensions: int = 2,
        config: Optional[BoidsConfig] = None,
    ) -> Boids:
        """Initialize Boids simulation."""
        if config is None:
            config = BoidsConfig(n_boids=n_boids, n_dimensions=n_dimensions)
        
        self._active_algorithm = Boids(config)
        self._algorithm_type = SwarmAlgorithm.BOIDS
        
        logger.info("Boids initialized: %d boids, %d dimensions", n_boids, n_dimensions)
        return self._active_algorithm
    
    def initialize_deep_swarm(
        self,
        n_agents: int = 10,
        config: Optional[DeepSwarmConfig] = None,
    ) -> DeepSwarm:
        """Initialize DeepSwarm for architecture search."""
        if config is None:
            config = DeepSwarmConfig(n_agents=n_agents)
        
        self._active_algorithm = DeepSwarm(config)
        self._algorithm_type = SwarmAlgorithm.DEEP_SWARM
        
        logger.info("DeepSwarm initialized: %d agents", n_agents)
        return self._active_algorithm
    
    def optimize(
        self,
        fitness_fn: Callable,
        n_iterations: int = 100,
        callback: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> OptimizationResult:
        """
        Run optimization with active algorithm.
        """
        if self._active_algorithm is None:
            raise RuntimeError("No algorithm initialized")
        
        logger.info("Starting %s optimization for %d iterations", 
                   self._algorithm_type.value, n_iterations)
        
        start_time = time.time()
        fitness_history = []
        
        # Run optimization based on algorithm type
        if self._algorithm_type == SwarmAlgorithm.PSO:
            result = self._active_algorithm.optimize(
                fitness_fn, n_iterations, callback
            )
            best_solution = result["best_position"]
            best_fitness = result["best_fitness"]
            fitness_history = self._active_algorithm._fitness_history
        
        elif self._algorithm_type == SwarmAlgorithm.ACO:
            result = self._active_algorithm.optimize(
                fitness_fn, n_iterations, callback
            )
            best_solution = result["best_path"]
            best_fitness = -result["best_cost"]  # ACO minimizes cost
            fitness_history = [-c for c in self._active_algorithm._cost_history]
        
        elif self._algorithm_type == SwarmAlgorithm.ABC:
            result = self._active_algorithm.optimize(
                fitness_fn, n_iterations, callback
            )
            best_solution = result["best_position"]
            best_fitness = result["best_fitness"]
            fitness_history = self._active_algorithm._fitness_history
        
        elif self._algorithm_type == SwarmAlgorithm.BOIDS:
            result = self._active_algorithm.simulate(
                n_iterations, dt=1.0, callback=callback
            )
            best_solution = result["final_centroid"]
            best_fitness = result["final_alignment"]
            fitness_history = []
        
        elif self._algorithm_type == SwarmAlgorithm.DEEP_SWARM:
            result = self._active_algorithm.search(
                fitness_fn, n_iterations, callback
            )
            best_solution = result["best_architecture"]
            best_fitness = result["best_fitness"]
            fitness_history = self._active_algorithm._fitness_history
        
        else:
            raise ValueError(f"Unknown algorithm: {self._algorithm_type}")
        
        elapsed = time.time() - start_time
        
        opt_result = OptimizationResult(
            algorithm=self._algorithm_type.value,
            best_solution=best_solution,
            best_fitness=best_fitness,
            n_iterations=n_iterations,
            elapsed_seconds=elapsed,
            fitness_history=fitness_history,
        )
        
        self._optimization_results.append(opt_result)
        
        logger.info(
            "Optimization complete: best_fitness=%.6f, elapsed=%.2fs",
            best_fitness, elapsed
        )
        
        return opt_result
    
    def compare_algorithms(
        self,
        fitness_fn: Callable,
        n_dimensions: int = 10,
        n_iterations: int = 100,
        algorithms: Optional[List[SwarmAlgorithm]] = None,
    ) -> Dict[str, OptimizationResult]:
        """
        Compare multiple algorithms on the same problem.
        """
        if algorithms is None:
            algorithms = [SwarmAlgorithm.PSO, SwarmAlgorithm.ABC]
        
        results = {}
        
        for algo in algorithms:
            logger.info("Running %s...", algo.value)
            
            if algo == SwarmAlgorithm.PSO:
                self.initialize_pso(n_dimensions=n_dimensions)
            elif algo == SwarmAlgorithm.ABC:
                self.initialize_abc(n_dimensions=n_dimensions)
            elif algo == SwarmAlgorithm.ACO:
                # ACO needs different setup
                continue
            else:
                continue
            
            result = self.optimize(fitness_fn, n_iterations)
            results[algo.value] = result
        
        # Log comparison
        logger.info("Algorithm comparison:")
        for name, result in results.items():
            logger.info("  %s: fitness=%.6f, time=%.2fs", 
                       name, result.best_fitness, result.elapsed_seconds)
        
        return results
    
    def get_algorithm(self) -> Optional[Any]:
        """Get active algorithm."""
        return self._active_algorithm
    
    def get_status(self) -> Dict[str, Any]:
        """Get coordinator status."""
        return {
            "algorithm": self._algorithm_type.value if self._algorithm_type else None,
            "algorithm_stats": self._active_algorithm.get_stats() if self._active_algorithm else None,
            "total_optimizations": len(self._optimization_results),
        }
    
    def get_optimization_history(self) -> List[Dict[str, Any]]:
        """Get optimization history."""
        return [r.to_dict() for r in self._optimization_results]


# Singleton instance
_swarm_coordinator: Optional[SwarmCoordinator] = None


def get_swarm_coordinator() -> SwarmCoordinator:
    """Get the singleton swarm coordinator."""
    global _swarm_coordinator
    if _swarm_coordinator is None:
        _swarm_coordinator = SwarmCoordinator()
    return _swarm_coordinator
