"""
MERID Swarm Intelligence - Particle Swarm Optimization (PSO)

PSO optimizes by simulating social behavior of bird flocking:
- Particles move through solution space
- Each particle remembers its best position
- Particles are attracted to global best and personal best
- Inertia controls exploration vs exploitation

Reference: Kennedy & Eberhart, "Particle Swarm Optimization"
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple
import numpy as np

from utils.logger import get_logger

logger = get_logger("learning.swarm.pso")


@dataclass
class PSOConfig:
    """Configuration for PSO."""
    # Swarm parameters
    n_particles: int = 30
    n_dimensions: int = 10
    
    # Velocity parameters
    w: float = 0.7        # Inertia weight
    c1: float = 1.5       # Cognitive (personal best) coefficient
    c2: float = 1.5       # Social (global best) coefficient
    
    # Velocity limits
    v_max: float = 1.0
    
    # Search bounds
    lower_bound: float = -10.0
    upper_bound: float = 10.0
    
    # Training
    n_iterations: int = 100
    
    # Adaptive parameters
    w_decay: float = 0.99  # Inertia decay per iteration
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "n_particles": self.n_particles,
            "n_dimensions": self.n_dimensions,
            "w": self.w,
            "c1": self.c1,
            "c2": self.c2,
            "n_iterations": self.n_iterations,
        }


@dataclass
class Particle:
    """A particle in the swarm."""
    particle_id: int
    position: np.ndarray
    velocity: np.ndarray
    
    # Personal best
    best_position: np.ndarray = None
    best_fitness: float = float('-inf')
    
    # Current fitness
    fitness: float = float('-inf')
    
    def __post_init__(self):
        if self.best_position is None:
            self.best_position = self.position.copy()
    
    def update_personal_best(self, fitness: float) -> bool:
        """Update personal best if current is better."""
        self.fitness = fitness
        if fitness > self.best_fitness:
            self.best_fitness = fitness
            self.best_position = self.position.copy()
            return True
        return False
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "particle_id": self.particle_id,
            "fitness": round(self.fitness, 6),
            "best_fitness": round(self.best_fitness, 6),
        }


class PSO:
    """
    Particle Swarm Optimization.
    
    Key features:
    - Population-based optimization
    - Balance between exploration and exploitation
    - No gradient required
    - Good for continuous optimization
    """
    
    def __init__(self, config: Optional[PSOConfig] = None):
        self.config = config or PSOConfig()
        
        # Initialize swarm
        self.particles: List[Particle] = []
        self._init_swarm()
        
        # Global best
        self.global_best_position: np.ndarray = None
        self.global_best_fitness: float = float('-inf')
        
        # Training state
        self._iteration = 0
        self._current_w = self.config.w
        
        # History
        self._fitness_history: List[float] = []
        self._diversity_history: List[float] = []
        
        logger.info(
            "PSO initialized: %d particles, %d dimensions",
            self.config.n_particles, self.config.n_dimensions
        )
    
    def _init_swarm(self) -> None:
        """Initialize particle swarm."""
        for i in range(self.config.n_particles):
            # Random initial position
            position = np.random.uniform(
                self.config.lower_bound,
                self.config.upper_bound,
                self.config.n_dimensions
            )
            
            # Random initial velocity
            velocity = np.random.uniform(
                -self.config.v_max,
                self.config.v_max,
                self.config.n_dimensions
            )
            
            particle = Particle(
                particle_id=i,
                position=position,
                velocity=velocity,
            )
            self.particles.append(particle)
    
    def evaluate(
        self,
        fitness_fn: Callable[[np.ndarray], float],
    ) -> None:
        """Evaluate all particles."""
        for particle in self.particles:
            fitness = fitness_fn(particle.position)
            improved = particle.update_personal_best(fitness)
            
            # Update global best
            if fitness > self.global_best_fitness:
                self.global_best_fitness = fitness
                self.global_best_position = particle.position.copy()
    
    def update_velocities(self) -> None:
        """Update particle velocities."""
        for particle in self.particles:
            r1 = np.random.random(self.config.n_dimensions)
            r2 = np.random.random(self.config.n_dimensions)
            
            # Cognitive component (personal best)
            cognitive = self.config.c1 * r1 * (particle.best_position - particle.position)
            
            # Social component (global best)
            social = self.config.c2 * r2 * (self.global_best_position - particle.position)
            
            # Update velocity
            particle.velocity = (
                self._current_w * particle.velocity +
                cognitive +
                social
            )
            
            # Clamp velocity
            particle.velocity = np.clip(
                particle.velocity,
                -self.config.v_max,
                self.config.v_max
            )
    
    def update_positions(self) -> None:
        """Update particle positions."""
        for particle in self.particles:
            particle.position += particle.velocity
            
            # Clamp to bounds
            particle.position = np.clip(
                particle.position,
                self.config.lower_bound,
                self.config.upper_bound
            )
    
    def step(
        self,
        fitness_fn: Callable[[np.ndarray], float],
    ) -> Dict[str, Any]:
        """Perform one optimization step."""
        self._iteration += 1
        
        # Evaluate
        self.evaluate(fitness_fn)
        
        # Update velocities and positions
        self.update_velocities()
        self.update_positions()
        
        # Decay inertia
        self._current_w *= self.config.w_decay
        
        # Track history
        self._fitness_history.append(self.global_best_fitness)
        self._diversity_history.append(self._compute_diversity())
        
        return {
            "iteration": self._iteration,
            "global_best_fitness": self.global_best_fitness,
            "avg_fitness": np.mean([p.fitness for p in self.particles]),
            "diversity": self._diversity_history[-1],
            "inertia": self._current_w,
        }
    
    def _compute_diversity(self) -> float:
        """Compute swarm diversity (average distance from centroid)."""
        positions = np.array([p.position for p in self.particles])
        centroid = positions.mean(axis=0)
        distances = np.linalg.norm(positions - centroid, axis=1)
        return float(distances.mean())
    
    def optimize(
        self,
        fitness_fn: Callable[[np.ndarray], float],
        n_iterations: Optional[int] = None,
        callback: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> Dict[str, Any]:
        """
        Run full optimization.
        
        Returns optimization result.
        """
        n_iterations = n_iterations or self.config.n_iterations
        
        logger.info("Starting PSO optimization for %d iterations", n_iterations)
        start_time = time.time()
        
        for i in range(n_iterations):
            info = self.step(fitness_fn)
            
            if callback:
                callback(info)
            
            if (i + 1) % 20 == 0:
                logger.info(
                    "Iteration %d: best_fitness=%.6f, diversity=%.4f",
                    i + 1, self.global_best_fitness, info["diversity"]
                )
        
        elapsed = time.time() - start_time
        
        return {
            "best_position": self.global_best_position.tolist(),
            "best_fitness": self.global_best_fitness,
            "n_iterations": n_iterations,
            "elapsed_seconds": elapsed,
            "final_diversity": self._diversity_history[-1] if self._diversity_history else 0,
        }
    
    def get_best_solution(self) -> Tuple[np.ndarray, float]:
        """Get best solution found."""
        return self.global_best_position.copy(), self.global_best_fitness
    
    def reset(self) -> None:
        """Reset swarm."""
        self.particles.clear()
        self._init_swarm()
        self.global_best_position = None
        self.global_best_fitness = float('-inf')
        self._iteration = 0
        self._current_w = self.config.w
        self._fitness_history.clear()
        self._diversity_history.clear()
    
    def get_stats(self) -> Dict[str, Any]:
        """Get optimization statistics."""
        return {
            "iteration": self._iteration,
            "global_best_fitness": round(self.global_best_fitness, 6) if self.global_best_fitness != float('-inf') else None,
            "n_particles": len(self.particles),
            "current_inertia": round(self._current_w, 4),
            "avg_particle_fitness": round(np.mean([p.fitness for p in self.particles]), 6),
        }
