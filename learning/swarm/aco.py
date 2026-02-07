"""
MERID Swarm Intelligence - Ant Colony Optimization (ACO)

ACO optimizes by simulating ant foraging behavior:
- Ants deposit pheromones on paths
- Better paths accumulate more pheromone
- Pheromone evaporates over time
- Ants probabilistically choose paths based on pheromone

Reference: Dorigo & Stützle, "Ant Colony Optimization"
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple
import numpy as np

from utils.logger import get_logger

logger = get_logger("learning.swarm.aco")


@dataclass
class ACOConfig:
    """Configuration for ACO."""
    # Colony parameters
    n_ants: int = 20
    n_nodes: int = 10
    
    # Pheromone parameters
    alpha: float = 1.0      # Pheromone importance
    beta: float = 2.0       # Heuristic importance
    rho: float = 0.1        # Evaporation rate
    q: float = 100.0        # Pheromone deposit factor
    
    # Initial pheromone
    tau_min: float = 0.01
    tau_max: float = 10.0
    tau_init: float = 1.0
    
    # Training
    n_iterations: int = 100
    
    # Elitism
    n_elite: int = 3
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "n_ants": self.n_ants,
            "n_nodes": self.n_nodes,
            "alpha": self.alpha,
            "beta": self.beta,
            "rho": self.rho,
            "n_iterations": self.n_iterations,
        }


@dataclass
class Ant:
    """An ant in the colony."""
    ant_id: int
    path: List[int] = field(default_factory=list)
    path_cost: float = float('inf')
    visited: set = field(default_factory=set)
    
    def reset(self, start_node: int) -> None:
        """Reset ant for new iteration."""
        self.path = [start_node]
        self.visited = {start_node}
        self.path_cost = float('inf')
    
    def visit(self, node: int) -> None:
        """Visit a node."""
        self.path.append(node)
        self.visited.add(node)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "ant_id": self.ant_id,
            "path_length": len(self.path),
            "path_cost": round(self.path_cost, 4) if self.path_cost != float('inf') else None,
        }


class ACO:
    """
    Ant Colony Optimization.
    
    Key features:
    - Good for combinatorial optimization (TSP, routing)
    - Emergent collective behavior
    - Adaptive through pheromone dynamics
    - Robust to local optima
    """
    
    def __init__(self, config: Optional[ACOConfig] = None):
        self.config = config or ACOConfig()
        
        # Initialize pheromone matrix
        self.pheromone = np.full(
            (self.config.n_nodes, self.config.n_nodes),
            self.config.tau_init
        )
        
        # Heuristic information (to be set by problem)
        self.heuristic = np.ones((self.config.n_nodes, self.config.n_nodes))
        
        # Initialize ants
        self.ants: List[Ant] = [
            Ant(ant_id=i) for i in range(self.config.n_ants)
        ]
        
        # Best solution
        self.best_path: List[int] = []
        self.best_cost: float = float('inf')
        
        # Training state
        self._iteration = 0
        
        # History
        self._cost_history: List[float] = []
        
        logger.info(
            "ACO initialized: %d ants, %d nodes",
            self.config.n_ants, self.config.n_nodes
        )
    
    def set_heuristic(self, heuristic: np.ndarray) -> None:
        """Set heuristic information matrix."""
        self.heuristic = heuristic
    
    def set_distance_matrix(self, distances: np.ndarray) -> None:
        """Set heuristic from distance matrix (inverse distance)."""
        with np.errstate(divide='ignore'):
            self.heuristic = 1.0 / (distances + 1e-10)
        self.heuristic[distances == 0] = 0
    
    def _select_next_node(self, ant: Ant) -> int:
        """Select next node for ant using probabilistic rule."""
        current = ant.path[-1]
        
        # Get unvisited nodes
        unvisited = [i for i in range(self.config.n_nodes) if i not in ant.visited]
        
        if not unvisited:
            return -1
        
        # Calculate probabilities
        probs = np.zeros(len(unvisited))
        
        for i, node in enumerate(unvisited):
            tau = self.pheromone[current, node]
            eta = self.heuristic[current, node]
            probs[i] = (tau ** self.config.alpha) * (eta ** self.config.beta)
        
        # Normalize
        total = probs.sum()
        if total > 0:
            probs /= total
        else:
            probs = np.ones(len(unvisited)) / len(unvisited)
        
        # Select node
        selected_idx = np.random.choice(len(unvisited), p=probs)
        return unvisited[selected_idx]
    
    def _construct_solutions(
        self,
        cost_fn: Callable[[List[int]], float],
    ) -> None:
        """Have all ants construct solutions."""
        for ant in self.ants:
            # Start from random node
            start = np.random.randint(0, self.config.n_nodes)
            ant.reset(start)
            
            # Construct path
            while len(ant.path) < self.config.n_nodes:
                next_node = self._select_next_node(ant)
                if next_node == -1:
                    break
                ant.visit(next_node)
            
            # Evaluate path
            ant.path_cost = cost_fn(ant.path)
            
            # Update best
            if ant.path_cost < self.best_cost:
                self.best_cost = ant.path_cost
                self.best_path = ant.path.copy()
    
    def _update_pheromone(self) -> None:
        """Update pheromone matrix."""
        # Evaporation
        self.pheromone *= (1 - self.config.rho)
        
        # Deposit pheromone
        for ant in self.ants:
            if ant.path_cost < float('inf'):
                deposit = self.config.q / ant.path_cost
                
                for i in range(len(ant.path) - 1):
                    from_node = ant.path[i]
                    to_node = ant.path[i + 1]
                    self.pheromone[from_node, to_node] += deposit
                    self.pheromone[to_node, from_node] += deposit
        
        # Elite ant bonus
        if self.best_path and self.best_cost < float('inf'):
            elite_deposit = self.config.n_elite * self.config.q / self.best_cost
            for i in range(len(self.best_path) - 1):
                from_node = self.best_path[i]
                to_node = self.best_path[i + 1]
                self.pheromone[from_node, to_node] += elite_deposit
                self.pheromone[to_node, from_node] += elite_deposit
        
        # Clamp pheromone
        self.pheromone = np.clip(
            self.pheromone,
            self.config.tau_min,
            self.config.tau_max
        )
    
    def step(
        self,
        cost_fn: Callable[[List[int]], float],
    ) -> Dict[str, Any]:
        """Perform one optimization step."""
        self._iteration += 1
        
        # Construct solutions
        self._construct_solutions(cost_fn)
        
        # Update pheromone
        self._update_pheromone()
        
        # Track history
        self._cost_history.append(self.best_cost)
        
        avg_cost = np.mean([a.path_cost for a in self.ants if a.path_cost < float('inf')])
        
        return {
            "iteration": self._iteration,
            "best_cost": self.best_cost,
            "avg_cost": avg_cost if not np.isnan(avg_cost) else float('inf'),
            "pheromone_mean": float(self.pheromone.mean()),
        }
    
    def optimize(
        self,
        cost_fn: Callable[[List[int]], float],
        n_iterations: Optional[int] = None,
        callback: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> Dict[str, Any]:
        """
        Run full optimization.
        """
        n_iterations = n_iterations or self.config.n_iterations
        
        logger.info("Starting ACO optimization for %d iterations", n_iterations)
        start_time = time.time()
        
        for i in range(n_iterations):
            info = self.step(cost_fn)
            
            if callback:
                callback(info)
            
            if (i + 1) % 20 == 0:
                logger.info(
                    "Iteration %d: best_cost=%.4f",
                    i + 1, self.best_cost
                )
        
        elapsed = time.time() - start_time
        
        return {
            "best_path": self.best_path,
            "best_cost": self.best_cost,
            "n_iterations": n_iterations,
            "elapsed_seconds": elapsed,
        }
    
    def get_best_solution(self) -> Tuple[List[int], float]:
        """Get best solution found."""
        return self.best_path.copy(), self.best_cost
    
    def reset(self) -> None:
        """Reset colony."""
        self.pheromone = np.full(
            (self.config.n_nodes, self.config.n_nodes),
            self.config.tau_init
        )
        self.best_path = []
        self.best_cost = float('inf')
        self._iteration = 0
        self._cost_history.clear()
    
    def get_stats(self) -> Dict[str, Any]:
        """Get optimization statistics."""
        return {
            "iteration": self._iteration,
            "best_cost": round(self.best_cost, 4) if self.best_cost != float('inf') else None,
            "n_ants": len(self.ants),
            "pheromone_mean": round(float(self.pheromone.mean()), 4),
            "pheromone_std": round(float(self.pheromone.std()), 4),
        }
