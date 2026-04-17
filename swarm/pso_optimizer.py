"""Stage 10: Particle Swarm Optimization (PSO) for hyperparameter tuning."""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

import numpy as np

from utils.logger import get_logger

logger = get_logger("swarm.pso")


@dataclass
class Particle:
    """PSO particle representing a hyperparameter configuration."""

    position: np.ndarray
    velocity: np.ndarray
    best_position: np.ndarray
    best_fitness: float = float("-inf")
    fitness: float = float("-inf")

    @classmethod
    def create(cls, bounds: List[Tuple[float, float]]) -> Particle:
        """Create a particle with random initialization."""
        dim = len(bounds)
        position = np.array([random.uniform(low, high) for low, high in bounds])
        velocity = np.array([random.uniform(-1, 1) for _ in range(dim)])
        return cls(
            position=position,
            velocity=velocity,
            best_position=position.copy(),
            best_fitness=float("-inf"),
            fitness=float("-inf"),
        )


@dataclass
class PSOConfig:
    """Configuration for PSO optimizer."""

    num_particles: int = 30
    max_iterations: int = 100
    w: float = 0.7  # Inertia weight
    c1: float = 1.5  # Cognitive coefficient
    c2: float = 1.5  # Social coefficient
    bounds: List[Tuple[float, float]] = field(default_factory=list)
    adaptive_inertia: bool = True
    velocity_clamping: bool = True
    topology: str = "global"  # global, ring, von_neumann


class PSOOptimizer:
    """Particle Swarm Optimization for hyperparameter tuning."""

    def __init__(self, config: PSOConfig):
        self.config = config
        self.particles: List[Particle] = []
        self.global_best_position: Optional[np.ndarray] = None
        self.global_best_fitness: float = float("-inf")
        self.iteration = 0
        self.fitness_history: List[float] = []
        self.diversity_history: List[float] = []

        self._initialize_swarm()

    def _initialize_swarm(self) -> None:
        """Initialize particle swarm."""
        for _ in range(self.config.num_particles):
            particle = Particle.create(self.config.bounds)
            self.particles.append(particle)

        logger.info(
            "PSO swarm initialized: particles=%d, dimensions=%d",
            self.config.num_particles,
            len(self.config.bounds),
        )

    def _update_inertia(self) -> float:
        """Adaptive inertia weight decay."""
        if self.config.adaptive_inertia:
            # Linear decay from 0.9 to 0.4
            w_max = 0.9
            w_min = 0.4
            return w_max - (w_max - w_min) * (self.iteration / self.config.max_iterations)
        return self.config.w

    def _clamp_velocity(self, velocity: np.ndarray) -> np.ndarray:
        """Clamp velocity to prevent explosion."""
        if not self.config.velocity_clamping:
            return velocity

        v_max = np.array([(high - low) * 0.2 for low, high in self.config.bounds])
        return np.clip(velocity, -v_max, v_max)

    def _clamp_position(self, position: np.ndarray) -> np.ndarray:
        """Clamp position to bounds."""
        clamped = position.copy()
        for i, (low, high) in enumerate(self.config.bounds):
            clamped[i] = np.clip(clamped[i], low, high)
        return clamped

    def _get_neighborhood_best(self, particle_idx: int) -> np.ndarray:
        """Get best position in particle's neighborhood based on topology."""
        if self.config.topology == "global":
            return self.global_best_position

        elif self.config.topology == "ring":
            # Ring topology: particle communicates with immediate neighbors
            n = len(self.particles)
            neighbors = [
                (particle_idx - 1) % n,
                particle_idx,
                (particle_idx + 1) % n,
            ]
            best_neighbor = max(neighbors, key=lambda i: self.particles[i].best_fitness)
            return self.particles[best_neighbor].best_position

        elif self.config.topology == "von_neumann":
            # Von Neumann topology: 2D grid with 4 neighbors
            n = len(self.particles)
            grid_size = int(np.sqrt(n))
            row = particle_idx // grid_size
            col = particle_idx % grid_size

            neighbors = [particle_idx]
            if row > 0:
                neighbors.append((row - 1) * grid_size + col)
            if row < grid_size - 1:
                neighbors.append((row + 1) * grid_size + col)
            if col > 0:
                neighbors.append(row * grid_size + (col - 1))
            if col < grid_size - 1:
                neighbors.append(row * grid_size + (col + 1))

            best_neighbor = max(neighbors, key=lambda i: self.particles[i].best_fitness)
            return self.particles[best_neighbor].best_position

        return self.global_best_position

    def _compute_diversity(self) -> float:
        """Compute swarm diversity (average distance from centroid)."""
        positions = np.array([p.position for p in self.particles])
        centroid = np.mean(positions, axis=0)
        distances = np.linalg.norm(positions - centroid, axis=1)
        return float(np.mean(distances))

    def optimize(
        self,
        fitness_fn: Callable[[np.ndarray], float],
        callback: Optional[Callable[[int, float, float], None]] = None,
    ) -> Tuple[np.ndarray, float]:
        """
        Run PSO optimization.

        Args:
            fitness_fn: Function that evaluates fitness of a position
            callback: Optional callback(iteration, best_fitness, diversity)

        Returns:
            (best_position, best_fitness)
        """
        for iteration in range(self.config.max_iterations):
            self.iteration = iteration

            # Evaluate fitness for all particles
            for particle in self.particles:
                particle.fitness = fitness_fn(particle.position)

                # Update personal best
                if particle.fitness > particle.best_fitness:
                    particle.best_fitness = particle.fitness
                    particle.best_position = particle.position.copy()

                # Update global best
                if particle.fitness > self.global_best_fitness:
                    self.global_best_fitness = particle.fitness
                    self.global_best_position = particle.position.copy()

            # Update velocities and positions
            w = self._update_inertia()

            for i, particle in enumerate(self.particles):
                r1 = np.random.random(len(particle.position))
                r2 = np.random.random(len(particle.position))

                neighborhood_best = self._get_neighborhood_best(i)

                # Velocity update
                cognitive = self.config.c1 * r1 * (particle.best_position - particle.position)
                social = self.config.c2 * r2 * (neighborhood_best - particle.position)
                particle.velocity = w * particle.velocity + cognitive + social

                # Clamp velocity
                particle.velocity = self._clamp_velocity(particle.velocity)

                # Position update
                particle.position = particle.position + particle.velocity
                particle.position = self._clamp_position(particle.position)

            # Track metrics
            self.fitness_history.append(self.global_best_fitness)
            diversity = self._compute_diversity()
            self.diversity_history.append(diversity)

            # Callback
            if callback:
                callback(iteration, self.global_best_fitness, diversity)

            # Logging
            if iteration % 10 == 0:
                logger.info(
                    "PSO iteration %d/%d: best_fitness=%.4f, diversity=%.4f",
                    iteration,
                    self.config.max_iterations,
                    self.global_best_fitness,
                    diversity,
                )

        logger.info(
            "PSO optimization complete: best_fitness=%.4f, position=%s",
            self.global_best_fitness,
            self.global_best_position,
        )

        return self.global_best_position, self.global_best_fitness

    def get_metrics(self) -> Dict[str, any]:
        """Get optimization metrics."""
        return {
            "iteration": self.iteration,
            "global_best_fitness": self.global_best_fitness,
            "global_best_position": self.global_best_position.tolist() if self.global_best_position is not None else None,
            "fitness_history": self.fitness_history,
            "diversity_history": self.diversity_history,
            "num_particles": len(self.particles),
            "particles": [
                {
                    "position": p.position.tolist(),
                    "fitness": p.fitness,
                    "best_fitness": p.best_fitness,
                }
                for p in self.particles[:5]  # Sample first 5
            ],
        }


# ---------------------------------------------------------------------------
# Hyperparameter Search Spaces
# ---------------------------------------------------------------------------


@dataclass
class MARLHyperparams:
    """MARL hyperparameter configuration."""

    learning_rate: float = 0.001
    gamma: float = 0.99
    epsilon_decay: float = 0.995
    batch_size: int = 64
    buffer_size: int = 10000
    hidden_size: int = 128

    @classmethod
    def from_position(cls, position: np.ndarray) -> MARLHyperparams:
        """Create hyperparams from PSO position."""
        return cls(
            learning_rate=position[0],
            gamma=position[1],
            epsilon_decay=position[2],
            batch_size=int(position[3]),
            buffer_size=int(position[4]),
            hidden_size=int(position[5]),
        )

    @classmethod
    def get_bounds(cls) -> List[Tuple[float, float]]:
        """Get PSO search bounds."""
        return [
            (0.0001, 0.01),  # learning_rate
            (0.9, 0.999),  # gamma
            (0.99, 0.9999),  # epsilon_decay
            (32, 256),  # batch_size
            (1000, 50000),  # buffer_size
            (64, 512),  # hidden_size
        ]


@dataclass
class ConsensusHyperparams:
    """Consensus mechanism hyperparameter configuration."""

    threshold: float = 0.6
    confidence_floor: float = 0.3
    trust_decay_rate: float = 0.03
    srw_success_weight: float = 0.6
    srw_fallback_weight: float = 0.3
    srw_latency_weight: float = 0.1

    @classmethod
    def from_position(cls, position: np.ndarray) -> ConsensusHyperparams:
        """Create hyperparams from PSO position."""
        return cls(
            threshold=position[0],
            confidence_floor=position[1],
            trust_decay_rate=position[2],
            srw_success_weight=position[3],
            srw_fallback_weight=position[4],
            srw_latency_weight=position[5],
        )

    @classmethod
    def get_bounds(cls) -> List[Tuple[float, float]]:
        """Get PSO search bounds."""
        return [
            (0.5, 0.8),  # threshold
            (0.1, 0.5),  # confidence_floor
            (0.01, 0.1),  # trust_decay_rate
            (0.4, 0.8),  # srw_success_weight
            (0.1, 0.4),  # srw_fallback_weight
            (0.05, 0.2),  # srw_latency_weight
        ]


# ---------------------------------------------------------------------------
# PSO-MARL Integration
# ---------------------------------------------------------------------------


class PSOMarLTuner:
    """Integrate PSO with MARL for hyperparameter optimization."""

    def __init__(
        self,
        marl_env_fn: Callable,
        num_particles: int = 20,
        max_iterations: int = 50,
    ):
        self.marl_env_fn = marl_env_fn
        self.pso_config = PSOConfig(
            num_particles=num_particles,
            max_iterations=max_iterations,
            bounds=MARLHyperparams.get_bounds(),
        )
        self.optimizer = PSOOptimizer(self.pso_config)
        self.best_hyperparams: Optional[MARLHyperparams] = None

    def fitness_function(self, position: np.ndarray) -> float:
        """Evaluate MARL performance with given hyperparameters."""
        hyperparams = MARLHyperparams.from_position(position)

        # Train MARL agents with these hyperparameters
        # This is a simplified evaluation - in production, run full training
        env = self.marl_env_fn()
        total_reward = 0.0

        # Simulate training episodes
        for episode in range(10):  # Quick evaluation
            episode_reward = env.run_episode(hyperparams)
            total_reward += episode_reward

        avg_reward = total_reward / 10
        logger.debug("PSO fitness evaluation: hyperparams=%s, reward=%.4f", hyperparams, avg_reward)

        return avg_reward

    def tune(self) -> MARLHyperparams:
        """Run PSO tuning and return best hyperparameters."""
        best_position, best_fitness = self.optimizer.optimize(self.fitness_function)
        self.best_hyperparams = MARLHyperparams.from_position(best_position)

        logger.info(
            "PSO-MARL tuning complete: best_fitness=%.4f, hyperparams=%s",
            best_fitness,
            self.best_hyperparams,
        )

        return self.best_hyperparams

    def get_metrics(self) -> Dict[str, any]:
        """Get tuning metrics."""
        return {
            "pso_metrics": self.optimizer.get_metrics(),
            "best_hyperparams": {
                "learning_rate": self.best_hyperparams.learning_rate if self.best_hyperparams else None,
                "gamma": self.best_hyperparams.gamma if self.best_hyperparams else None,
                "epsilon_decay": self.best_hyperparams.epsilon_decay if self.best_hyperparams else None,
                "batch_size": self.best_hyperparams.batch_size if self.best_hyperparams else None,
            }
            if self.best_hyperparams
            else None,
        }


# ---------------------------------------------------------------------------
# Reward Shaping Variants
# ---------------------------------------------------------------------------


class RewardShaper:
    """Reward shaping for MARL agents."""

    @staticmethod
    def difference_rewards(
        agent_idx: int,
        team_reward: float,
        counterfactual_reward: float,
    ) -> float:
        """
        Difference rewards: agent's contribution = team_reward - counterfactual.
        Counterfactual = reward if agent took default action.
        """
        return team_reward - counterfactual_reward

    @staticmethod
    def potential_based_shaping(
        state: np.ndarray,
        next_state: np.ndarray,
        gamma: float,
        potential_fn: Callable[[np.ndarray], float],
    ) -> float:
        """
        Potential-based reward shaping (preserves optimal policy).
        F(s, s') = γ * Φ(s') - Φ(s)
        """
        return gamma * potential_fn(next_state) - potential_fn(state)

    @staticmethod
    def curiosity_bonus(
        prediction_error: float,
        scale: float = 0.1,
    ) -> float:
        """
        Curiosity-driven exploration bonus based on prediction error.
        Encourages agents to explore novel states.
        """
        return scale * prediction_error

    @staticmethod
    def social_influence_reward(
        agent_action: int,
        other_agents_actions: List[int],
        coordination_bonus: float = 0.5,
    ) -> float:
        """
        Social influence reward: bonus for coordinating with other agents.
        Encourages cooperative behavior.
        """
        coordination_count = sum(1 for a in other_agents_actions if a == agent_action)
        return coordination_bonus * (coordination_count / len(other_agents_actions))

    @staticmethod
    def combined_reward(
        base_reward: float,
        difference_reward: float,
        curiosity_bonus: float,
        social_reward: float,
        weights: Tuple[float, float, float, float] = (0.5, 0.2, 0.2, 0.1),
    ) -> float:
        """Combine multiple reward components with weights."""
        return (
            weights[0] * base_reward
            + weights[1] * difference_reward
            + weights[2] * curiosity_bonus
            + weights[3] * social_reward
        )
