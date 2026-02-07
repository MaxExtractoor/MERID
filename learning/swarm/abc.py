"""
MERID Swarm Intelligence - Artificial Bee Colony (ABC)

ABC optimizes by simulating honey bee foraging behavior:
- Employed bees exploit known food sources
- Onlooker bees select sources based on quality
- Scout bees explore new random sources
- Abandonment mechanism prevents stagnation

Reference: Karaboga, "An Idea Based on Honey Bee Swarm for Numerical Optimization"
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple
import numpy as np

from utils.logger import get_logger

logger = get_logger("learning.swarm.abc")


class BeeRole(Enum):
    """Roles in the bee colony."""
    EMPLOYED = "employed"
    ONLOOKER = "onlooker"
    SCOUT = "scout"


@dataclass
class ABCConfig:
    """Configuration for ABC."""
    # Colony parameters
    n_employed: int = 20
    n_onlookers: int = 20
    n_dimensions: int = 10
    
    # Search bounds
    lower_bound: float = -10.0
    upper_bound: float = 10.0
    
    # Abandonment
    limit: int = 50  # Trials before abandonment
    
    # Training
    n_iterations: int = 100
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "n_employed": self.n_employed,
            "n_onlookers": self.n_onlookers,
            "n_dimensions": self.n_dimensions,
            "limit": self.limit,
            "n_iterations": self.n_iterations,
        }


@dataclass
class Bee:
    """A bee in the colony."""
    bee_id: int
    role: BeeRole
    position: np.ndarray
    fitness: float = float('-inf')
    trials: int = 0  # Trials without improvement
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "bee_id": self.bee_id,
            "role": self.role.value,
            "fitness": round(self.fitness, 6) if self.fitness != float('-inf') else None,
            "trials": self.trials,
        }


class FoodSource:
    """A food source (solution)."""
    
    def __init__(self, position: np.ndarray):
        self.position = position.copy()
        self.fitness: float = float('-inf')
        self.trials: int = 0
    
    def update(self, new_position: np.ndarray, new_fitness: float) -> bool:
        """Update if new solution is better."""
        if new_fitness > self.fitness:
            self.position = new_position.copy()
            self.fitness = new_fitness
            self.trials = 0
            return True
        else:
            self.trials += 1
            return False


class ABC:
    """
    Artificial Bee Colony Optimization.
    
    Key features:
    - Three bee types with different roles
    - Balance between exploitation and exploration
    - Automatic abandonment of poor solutions
    - Good for continuous optimization
    """
    
    def __init__(self, config: Optional[ABCConfig] = None):
        self.config = config or ABCConfig()
        
        # Initialize food sources (one per employed bee)
        self.food_sources: List[FoodSource] = []
        self._init_food_sources()
        
        # Best solution
        self.best_position: np.ndarray = None
        self.best_fitness: float = float('-inf')
        
        # Training state
        self._iteration = 0
        
        # History
        self._fitness_history: List[float] = []
        
        logger.info(
            "ABC initialized: %d employed, %d onlookers, %d dimensions",
            self.config.n_employed, self.config.n_onlookers, self.config.n_dimensions
        )
    
    def _init_food_sources(self) -> None:
        """Initialize food sources randomly."""
        for _ in range(self.config.n_employed):
            position = np.random.uniform(
                self.config.lower_bound,
                self.config.upper_bound,
                self.config.n_dimensions
            )
            self.food_sources.append(FoodSource(position))
    
    def _generate_neighbor(self, source_idx: int) -> np.ndarray:
        """Generate neighbor solution."""
        source = self.food_sources[source_idx]
        
        # Select random dimension
        dim = np.random.randint(0, self.config.n_dimensions)
        
        # Select random other source
        other_idx = np.random.choice([i for i in range(len(self.food_sources)) if i != source_idx])
        other = self.food_sources[other_idx]
        
        # Generate neighbor
        phi = np.random.uniform(-1, 1)
        neighbor = source.position.copy()
        neighbor[dim] = source.position[dim] + phi * (source.position[dim] - other.position[dim])
        
        # Clamp to bounds
        neighbor = np.clip(neighbor, self.config.lower_bound, self.config.upper_bound)
        
        return neighbor
    
    def _employed_bee_phase(
        self,
        fitness_fn: Callable[[np.ndarray], float],
    ) -> None:
        """Employed bees exploit their food sources."""
        for i, source in enumerate(self.food_sources):
            # Generate neighbor
            neighbor = self._generate_neighbor(i)
            neighbor_fitness = fitness_fn(neighbor)
            
            # Greedy selection
            source.update(neighbor, neighbor_fitness)
            
            # Update global best
            if source.fitness > self.best_fitness:
                self.best_fitness = source.fitness
                self.best_position = source.position.copy()
    
    def _calculate_probabilities(self) -> np.ndarray:
        """Calculate selection probabilities for onlooker bees."""
        fitnesses = np.array([s.fitness for s in self.food_sources])
        
        # Handle negative fitness
        min_fitness = fitnesses.min()
        if min_fitness < 0:
            fitnesses = fitnesses - min_fitness + 1
        
        # Normalize
        total = fitnesses.sum()
        if total > 0:
            probs = fitnesses / total
        else:
            probs = np.ones(len(self.food_sources)) / len(self.food_sources)
        
        return probs
    
    def _onlooker_bee_phase(
        self,
        fitness_fn: Callable[[np.ndarray], float],
    ) -> None:
        """Onlooker bees select and exploit food sources."""
        probs = self._calculate_probabilities()
        
        for _ in range(self.config.n_onlookers):
            # Select food source based on probability
            source_idx = np.random.choice(len(self.food_sources), p=probs)
            source = self.food_sources[source_idx]
            
            # Generate neighbor
            neighbor = self._generate_neighbor(source_idx)
            neighbor_fitness = fitness_fn(neighbor)
            
            # Greedy selection
            source.update(neighbor, neighbor_fitness)
            
            # Update global best
            if source.fitness > self.best_fitness:
                self.best_fitness = source.fitness
                self.best_position = source.position.copy()
    
    def _scout_bee_phase(
        self,
        fitness_fn: Callable[[np.ndarray], float],
    ) -> None:
        """Scout bees replace abandoned food sources."""
        for i, source in enumerate(self.food_sources):
            if source.trials >= self.config.limit:
                # Abandon and create new random source
                new_position = np.random.uniform(
                    self.config.lower_bound,
                    self.config.upper_bound,
                    self.config.n_dimensions
                )
                new_fitness = fitness_fn(new_position)
                
                source.position = new_position
                source.fitness = new_fitness
                source.trials = 0
                
                # Update global best
                if new_fitness > self.best_fitness:
                    self.best_fitness = new_fitness
                    self.best_position = new_position.copy()
    
    def step(
        self,
        fitness_fn: Callable[[np.ndarray], float],
    ) -> Dict[str, Any]:
        """Perform one optimization step."""
        self._iteration += 1
        
        # Three phases
        self._employed_bee_phase(fitness_fn)
        self._onlooker_bee_phase(fitness_fn)
        self._scout_bee_phase(fitness_fn)
        
        # Track history
        self._fitness_history.append(self.best_fitness)
        
        avg_fitness = np.mean([s.fitness for s in self.food_sources])
        abandoned = sum(1 for s in self.food_sources if s.trials >= self.config.limit)
        
        return {
            "iteration": self._iteration,
            "best_fitness": self.best_fitness,
            "avg_fitness": avg_fitness,
            "abandoned_sources": abandoned,
        }
    
    def optimize(
        self,
        fitness_fn: Callable[[np.ndarray], float],
        n_iterations: Optional[int] = None,
        callback: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> Dict[str, Any]:
        """Run full optimization."""
        n_iterations = n_iterations or self.config.n_iterations
        
        logger.info("Starting ABC optimization for %d iterations", n_iterations)
        start_time = time.time()
        
        # Initial evaluation
        for source in self.food_sources:
            source.fitness = fitness_fn(source.position)
            if source.fitness > self.best_fitness:
                self.best_fitness = source.fitness
                self.best_position = source.position.copy()
        
        for i in range(n_iterations):
            info = self.step(fitness_fn)
            
            if callback:
                callback(info)
            
            if (i + 1) % 20 == 0:
                logger.info(
                    "Iteration %d: best_fitness=%.6f",
                    i + 1, self.best_fitness
                )
        
        elapsed = time.time() - start_time
        
        return {
            "best_position": self.best_position.tolist() if self.best_position is not None else None,
            "best_fitness": self.best_fitness,
            "n_iterations": n_iterations,
            "elapsed_seconds": elapsed,
        }
    
    def get_best_solution(self) -> Tuple[np.ndarray, float]:
        """Get best solution found."""
        return self.best_position.copy() if self.best_position is not None else None, self.best_fitness
    
    def reset(self) -> None:
        """Reset colony."""
        self.food_sources.clear()
        self._init_food_sources()
        self.best_position = None
        self.best_fitness = float('-inf')
        self._iteration = 0
        self._fitness_history.clear()
    
    def get_stats(self) -> Dict[str, Any]:
        """Get optimization statistics."""
        return {
            "iteration": self._iteration,
            "best_fitness": round(self.best_fitness, 6) if self.best_fitness != float('-inf') else None,
            "n_food_sources": len(self.food_sources),
            "avg_trials": round(np.mean([s.trials for s in self.food_sources]), 2),
        }
