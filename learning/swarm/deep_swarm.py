"""
MERID Swarm Intelligence - DeepSwarm (Neural Architecture Search)

DeepSwarm uses swarm intelligence for neural architecture search:
- Agents explore the architecture space
- Pheromone-like signals guide search
- Emergent discovery of optimal architectures
- Combines ACO principles with deep learning

Reference: Byla & Pang, "DeepSwarm: Optimising Convolutional Neural Networks using Swarm Intelligence"
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple
import numpy as np

from utils.logger import get_logger

logger = get_logger("learning.swarm.deep_swarm")


class LayerType(Enum):
    """Types of neural network layers."""
    DENSE = "dense"
    CONV = "conv"
    POOL = "pool"
    DROPOUT = "dropout"
    BATCH_NORM = "batch_norm"
    ACTIVATION = "activation"
    SKIP = "skip"


@dataclass
class LayerConfig:
    """Configuration for a layer."""
    layer_type: LayerType
    units: int = 64
    kernel_size: int = 3
    dropout_rate: float = 0.2
    activation: str = "relu"
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "layer_type": self.layer_type.value,
            "units": self.units,
            "kernel_size": self.kernel_size,
            "dropout_rate": self.dropout_rate,
            "activation": self.activation,
        }


@dataclass
class Architecture:
    """A neural network architecture."""
    arch_id: str
    layers: List[LayerConfig] = field(default_factory=list)
    fitness: float = 0.0
    params_count: int = 0
    
    def add_layer(self, layer: LayerConfig) -> None:
        """Add a layer to architecture."""
        self.layers.append(layer)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "arch_id": self.arch_id,
            "n_layers": len(self.layers),
            "layers": [l.to_dict() for l in self.layers],
            "fitness": round(self.fitness, 6),
            "params_count": self.params_count,
        }


@dataclass
class DeepSwarmConfig:
    """Configuration for DeepSwarm."""
    # Swarm parameters
    n_agents: int = 10
    n_iterations: int = 50
    
    # Architecture constraints
    min_layers: int = 2
    max_layers: int = 10
    
    # Layer options
    dense_units: List[int] = field(default_factory=lambda: [32, 64, 128, 256, 512])
    kernel_sizes: List[int] = field(default_factory=lambda: [3, 5, 7])
    dropout_rates: List[float] = field(default_factory=lambda: [0.1, 0.2, 0.3, 0.5])
    activations: List[str] = field(default_factory=lambda: ["relu", "tanh", "sigmoid"])
    
    # Pheromone parameters
    pheromone_init: float = 1.0
    pheromone_evap: float = 0.1
    pheromone_deposit: float = 1.0
    
    # Selection
    alpha: float = 1.0  # Pheromone importance
    beta: float = 2.0   # Heuristic importance
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "n_agents": self.n_agents,
            "n_iterations": self.n_iterations,
            "min_layers": self.min_layers,
            "max_layers": self.max_layers,
        }


class ArchitectureGraph:
    """
    Graph representation of architecture search space.
    
    Nodes represent layer choices, edges represent transitions.
    """
    
    def __init__(self, config: DeepSwarmConfig):
        self.config = config
        
        # Build layer options
        self.layer_options: List[LayerConfig] = []
        self._build_layer_options()
        
        # Pheromone matrix: [from_layer_idx, to_layer_idx]
        n_options = len(self.layer_options) + 1  # +1 for "end" node
        self.pheromone = np.full((n_options, n_options), config.pheromone_init)
        
        # Heuristic (can be set based on prior knowledge)
        self.heuristic = np.ones((n_options, n_options))
    
    def _build_layer_options(self) -> None:
        """Build all possible layer configurations."""
        # Dense layers
        for units in self.config.dense_units:
            for activation in self.config.activations:
                self.layer_options.append(LayerConfig(
                    layer_type=LayerType.DENSE,
                    units=units,
                    activation=activation,
                ))
        
        # Dropout layers
        for rate in self.config.dropout_rates:
            self.layer_options.append(LayerConfig(
                layer_type=LayerType.DROPOUT,
                dropout_rate=rate,
            ))
        
        # Batch norm
        self.layer_options.append(LayerConfig(
            layer_type=LayerType.BATCH_NORM,
        ))
    
    def get_transition_prob(
        self,
        from_idx: int,
        to_idx: int,
    ) -> float:
        """Get transition probability."""
        tau = self.pheromone[from_idx, to_idx]
        eta = self.heuristic[from_idx, to_idx]
        return (tau ** self.config.alpha) * (eta ** self.config.beta)
    
    def select_next_layer(
        self,
        current_idx: int,
        n_layers: int,
    ) -> int:
        """Select next layer using probabilistic rule."""
        n_options = len(self.layer_options) + 1
        
        # Calculate probabilities
        probs = np.zeros(n_options)
        for i in range(n_options):
            probs[i] = self.get_transition_prob(current_idx, i)
        
        # Adjust for constraints
        if n_layers < self.config.min_layers:
            probs[-1] = 0  # Can't end yet
        if n_layers >= self.config.max_layers:
            probs[:-1] = 0  # Must end
            probs[-1] = 1
        
        # Normalize
        total = probs.sum()
        if total > 0:
            probs /= total
        else:
            probs[-1] = 1  # Default to end
        
        return int(np.random.choice(n_options, p=probs))
    
    def deposit_pheromone(
        self,
        path: List[int],
        fitness: float,
    ) -> None:
        """Deposit pheromone on path."""
        deposit = self.config.pheromone_deposit * fitness
        
        for i in range(len(path) - 1):
            self.pheromone[path[i], path[i + 1]] += deposit
    
    def evaporate_pheromone(self) -> None:
        """Evaporate pheromone."""
        self.pheromone *= (1 - self.config.pheromone_evap)
        self.pheromone = np.maximum(self.pheromone, 0.01)  # Minimum pheromone


class DeepSwarmAgent:
    """An agent that explores architecture space."""
    
    def __init__(self, agent_id: int):
        self.agent_id = agent_id
        self.current_architecture: Optional[Architecture] = None
        self.path: List[int] = []
    
    def construct_architecture(
        self,
        graph: ArchitectureGraph,
    ) -> Architecture:
        """Construct an architecture by traversing the graph."""
        arch = Architecture(arch_id=f"arch_{self.agent_id}_{int(time.time())}")
        self.path = [0]  # Start node
        
        current_idx = 0
        n_layers = 0
        
        while True:
            next_idx = graph.select_next_layer(current_idx, n_layers)
            self.path.append(next_idx)
            
            if next_idx == len(graph.layer_options):
                # End node reached
                break
            
            # Add layer
            layer = graph.layer_options[next_idx]
            arch.add_layer(layer)
            n_layers += 1
            current_idx = next_idx
        
        self.current_architecture = arch
        return arch


class DeepSwarm:
    """
    DeepSwarm Neural Architecture Search.
    
    Key features:
    - Swarm-based architecture exploration
    - Pheromone-guided search
    - Automatic architecture discovery
    - Balances exploration and exploitation
    """
    
    def __init__(self, config: Optional[DeepSwarmConfig] = None):
        self.config = config or DeepSwarmConfig()
        
        # Architecture graph
        self.graph = ArchitectureGraph(self.config)
        
        # Agents
        self.agents: List[DeepSwarmAgent] = [
            DeepSwarmAgent(i) for i in range(self.config.n_agents)
        ]
        
        # Best architecture
        self.best_architecture: Optional[Architecture] = None
        self.best_fitness: float = float('-inf')
        
        # History
        self._iteration = 0
        self._fitness_history: List[float] = []
        self._architectures: List[Architecture] = []
        
        logger.info(
            "DeepSwarm initialized: %d agents, %d layer options",
            self.config.n_agents, len(self.graph.layer_options)
        )
    
    def _evaluate_architecture(
        self,
        arch: Architecture,
        fitness_fn: Callable[[Architecture], float],
    ) -> float:
        """Evaluate an architecture."""
        fitness = fitness_fn(arch)
        arch.fitness = fitness
        return fitness
    
    def step(
        self,
        fitness_fn: Callable[[Architecture], float],
    ) -> Dict[str, Any]:
        """Perform one search iteration."""
        self._iteration += 1
        
        # Each agent constructs an architecture
        architectures = []
        for agent in self.agents:
            arch = agent.construct_architecture(self.graph)
            fitness = self._evaluate_architecture(arch, fitness_fn)
            architectures.append(arch)
            
            # Update best
            if fitness > self.best_fitness:
                self.best_fitness = fitness
                self.best_architecture = arch
        
        # Deposit pheromone
        for agent, arch in zip(self.agents, architectures):
            if arch.fitness > 0:
                self.graph.deposit_pheromone(agent.path, arch.fitness)
        
        # Evaporate pheromone
        self.graph.evaporate_pheromone()
        
        # Track history
        self._fitness_history.append(self.best_fitness)
        self._architectures.extend(architectures)
        
        avg_fitness = np.mean([a.fitness for a in architectures])
        avg_layers = np.mean([len(a.layers) for a in architectures])
        
        return {
            "iteration": self._iteration,
            "best_fitness": self.best_fitness,
            "avg_fitness": avg_fitness,
            "avg_layers": avg_layers,
            "n_architectures": len(self._architectures),
        }
    
    def search(
        self,
        fitness_fn: Callable[[Architecture], float],
        n_iterations: Optional[int] = None,
        callback: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> Dict[str, Any]:
        """
        Run full architecture search.
        
        fitness_fn: Function that evaluates an architecture and returns fitness.
        """
        n_iterations = n_iterations or self.config.n_iterations
        
        logger.info("Starting DeepSwarm search for %d iterations", n_iterations)
        start_time = time.time()
        
        for i in range(n_iterations):
            info = self.step(fitness_fn)
            
            if callback:
                callback(info)
            
            if (i + 1) % 10 == 0:
                logger.info(
                    "Iteration %d: best_fitness=%.6f, best_layers=%d",
                    i + 1, self.best_fitness,
                    len(self.best_architecture.layers) if self.best_architecture else 0
                )
        
        elapsed = time.time() - start_time
        
        return {
            "best_architecture": self.best_architecture.to_dict() if self.best_architecture else None,
            "best_fitness": self.best_fitness,
            "n_iterations": n_iterations,
            "total_architectures_evaluated": len(self._architectures),
            "elapsed_seconds": elapsed,
        }
    
    def get_top_architectures(self, n: int = 5) -> List[Architecture]:
        """Get top n architectures by fitness."""
        sorted_archs = sorted(self._architectures, key=lambda a: a.fitness, reverse=True)
        return sorted_archs[:n]
    
    def reset(self) -> None:
        """Reset search."""
        self.graph = ArchitectureGraph(self.config)
        self.best_architecture = None
        self.best_fitness = float('-inf')
        self._iteration = 0
        self._fitness_history.clear()
        self._architectures.clear()
    
    def get_stats(self) -> Dict[str, Any]:
        """Get search statistics."""
        return {
            "iteration": self._iteration,
            "best_fitness": round(self.best_fitness, 6) if self.best_fitness != float('-inf') else None,
            "best_n_layers": len(self.best_architecture.layers) if self.best_architecture else 0,
            "total_architectures": len(self._architectures),
            "n_layer_options": len(self.graph.layer_options),
        }
