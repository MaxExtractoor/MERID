"""
MERID MARL Coordinator

Coordinates multiple MARL algorithms and manages training.
Integrates with MERID-OPS for regime awareness and MERID-GOV for approval.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple, Type
import numpy as np

from learning.marl.base import (
    MARLAgent,
    Trajectory,
    Experience,
    MultiAgentEnvironment,
)
from learning.marl.mappo import MAPPO, MAPPOConfig
from learning.marl.coma import COMA, COMAConfig
from learning.marl.qmix import QMIX, QMIXConfig
from learning.marl.vdn import VDN, VDNConfig
from learning.marl.ippo import IPPO, IPPOConfig
from utils.logger import get_logger

logger = get_logger("learning.marl.coordinator")


class MARLAlgorithm(Enum):
    """Available MARL algorithms."""
    MAPPO = "mappo"
    COMA = "coma"
    QMIX = "qmix"
    VDN = "vdn"
    IPPO = "ippo"


@dataclass
class TrainingConfig:
    """Configuration for MARL training."""
    algorithm: MARLAlgorithm = MARLAlgorithm.MAPPO
    
    # Training parameters
    n_episodes: int = 1000
    max_steps_per_episode: int = 200
    eval_interval: int = 50
    save_interval: int = 100
    
    # Environment
    n_agents: int = 3
    state_dim: int = 64
    action_dim: int = 5
    global_state_dim: int = 128
    
    # Early stopping
    target_reward: float = float('inf')
    patience: int = 50
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "algorithm": self.algorithm.value,
            "n_episodes": self.n_episodes,
            "max_steps_per_episode": self.max_steps_per_episode,
            "n_agents": self.n_agents,
        }


@dataclass
class TrainingResult:
    """Result of a training run."""
    algorithm: str
    n_episodes: int
    total_steps: int
    
    # Performance
    final_reward: float
    best_reward: float
    avg_reward: float
    
    # Timing
    training_time_seconds: float
    
    # History
    reward_history: List[float] = field(default_factory=list)
    loss_history: List[float] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "algorithm": self.algorithm,
            "n_episodes": self.n_episodes,
            "total_steps": self.total_steps,
            "final_reward": round(self.final_reward, 4),
            "best_reward": round(self.best_reward, 4),
            "avg_reward": round(self.avg_reward, 4),
            "training_time_seconds": round(self.training_time_seconds, 2),
        }


class MARLCoordinator:
    """
    Coordinates MARL training and evaluation.
    
    Responsibilities:
    - Algorithm selection and initialization
    - Training loop management
    - Integration with MERID systems (OPS, GOV)
    - Performance tracking and logging
    """
    
    ALGORITHM_CLASSES = {
        MARLAlgorithm.MAPPO: MAPPO,
        MARLAlgorithm.COMA: COMA,
        MARLAlgorithm.QMIX: QMIX,
        MARLAlgorithm.VDN: VDN,
        MARLAlgorithm.IPPO: IPPO,
    }
    
    def __init__(self):
        self._active_algorithm: Optional[Any] = None
        self._algorithm_type: Optional[MARLAlgorithm] = None
        
        # Training state
        self._is_training = False
        self._current_episode = 0
        self._total_steps = 0
        
        # Performance tracking
        self._reward_history: List[float] = []
        self._loss_history: List[float] = []
        self._best_reward = float('-inf')
        
        # Results
        self._training_results: List[TrainingResult] = []
        
        logger.info("MARL Coordinator initialized")
    
    def initialize_algorithm(
        self,
        algorithm: MARLAlgorithm,
        n_agents: int,
        state_dim: int,
        action_dim: int,
        global_state_dim: int = 0,
        config: Optional[Any] = None,
    ) -> Any:
        """Initialize a MARL algorithm."""
        logger.info("Initializing %s with %d agents", algorithm.value, n_agents)
        
        if algorithm == MARLAlgorithm.MAPPO:
            config = config or MAPPOConfig()
            self._active_algorithm = MAPPO(
                n_agents, state_dim, action_dim, global_state_dim, config
            )
        
        elif algorithm == MARLAlgorithm.COMA:
            config = config or COMAConfig()
            self._active_algorithm = COMA(
                n_agents, state_dim, action_dim, global_state_dim, config
            )
        
        elif algorithm == MARLAlgorithm.QMIX:
            config = config or QMIXConfig()
            self._active_algorithm = QMIX(
                n_agents, state_dim, action_dim, global_state_dim, config
            )
        
        elif algorithm == MARLAlgorithm.VDN:
            config = config or VDNConfig()
            self._active_algorithm = VDN(
                n_agents, state_dim, action_dim, config
            )
        
        elif algorithm == MARLAlgorithm.IPPO:
            config = config or IPPOConfig()
            self._active_algorithm = IPPO(
                n_agents, state_dim, action_dim, config
            )
        
        else:
            raise ValueError(f"Unknown algorithm: {algorithm}")
        
        self._algorithm_type = algorithm
        
        return self._active_algorithm
    
    def train_episode(
        self,
        env: MultiAgentEnvironment,
        max_steps: int = 200,
    ) -> Tuple[float, Dict[str, Any]]:
        """
        Train for one episode.
        
        Returns (total_reward, info).
        """
        if self._active_algorithm is None:
            raise RuntimeError("No algorithm initialized")
        
        self._current_episode += 1
        
        # Reset environment
        observations = env.reset()
        global_state = env.get_global_state()
        
        # Collect trajectories
        trajectories: Dict[str, Trajectory] = {
            agent_id: Trajectory(agent_id=agent_id)
            for agent_id in env.agent_ids
        }
        global_states = [global_state]
        joint_actions = []
        
        total_reward = 0.0
        
        for step in range(max_steps):
            self._total_steps += 1
            
            # Get actions
            actions_with_probs = self._active_algorithm.get_actions(observations)
            actions = {k: v[0] for k, v in actions_with_probs.items()}
            
            # Step environment
            next_observations, rewards, dones, infos = env.step(actions)
            next_global_state = env.get_global_state()
            
            # Record experiences
            for agent_id in env.agent_ids:
                if agent_id in observations:
                    exp = Experience(
                        state=observations[agent_id],
                        action=actions.get(agent_id, 0),
                        reward=rewards.get(agent_id, 0),
                        next_state=next_observations.get(agent_id, observations[agent_id]),
                        done=dones.get(agent_id, False),
                        agent_id=agent_id,
                        global_state=global_state,
                    )
                    trajectories[agent_id].add(exp)
            
            global_states.append(next_global_state)
            joint_actions.append(actions)
            
            total_reward += sum(rewards.values())
            
            # Check if done
            if all(dones.values()):
                break
            
            observations = next_observations
            global_state = next_global_state
        
        # Update algorithm
        update_info = self._update_algorithm(trajectories, global_states, joint_actions)
        
        # Track performance
        self._reward_history.append(total_reward)
        if total_reward > self._best_reward:
            self._best_reward = total_reward
        
        return total_reward, update_info
    
    def _update_algorithm(
        self,
        trajectories: Dict[str, Trajectory],
        global_states: List[np.ndarray],
        joint_actions: List[Dict[str, int]],
    ) -> Dict[str, Any]:
        """Update the active algorithm."""
        if self._active_algorithm is None:
            return {}
        
        if self._algorithm_type == MARLAlgorithm.MAPPO:
            processed = self._active_algorithm.collect_trajectories(
                trajectories, global_states
            )
            return self._active_algorithm.update(processed, np.array(global_states))
        
        elif self._algorithm_type == MARLAlgorithm.COMA:
            return self._active_algorithm.update(
                trajectories, global_states, joint_actions
            )
        
        elif self._algorithm_type == MARLAlgorithm.QMIX:
            return self._active_algorithm.update()
        
        elif self._algorithm_type == MARLAlgorithm.VDN:
            return self._active_algorithm.update()
        
        elif self._algorithm_type == MARLAlgorithm.IPPO:
            processed = self._active_algorithm.collect_trajectories(trajectories)
            return self._active_algorithm.update(processed)
        
        return {}
    
    def evaluate(
        self,
        env: MultiAgentEnvironment,
        n_episodes: int = 10,
        max_steps: int = 200,
    ) -> Dict[str, Any]:
        """Evaluate current policy."""
        if self._active_algorithm is None:
            raise RuntimeError("No algorithm initialized")
        
        rewards = []
        
        for _ in range(n_episodes):
            observations = env.reset()
            episode_reward = 0.0
            
            for step in range(max_steps):
                actions_with_probs = self._active_algorithm.get_actions(
                    observations, deterministic=True
                )
                actions = {k: v[0] for k, v in actions_with_probs.items()}
                
                next_observations, step_rewards, dones, _ = env.step(actions)
                episode_reward += sum(step_rewards.values())
                
                if all(dones.values()):
                    break
                
                observations = next_observations
            
            rewards.append(episode_reward)
        
        return {
            "mean_reward": np.mean(rewards),
            "std_reward": np.std(rewards),
            "min_reward": np.min(rewards),
            "max_reward": np.max(rewards),
            "n_episodes": n_episodes,
        }
    
    def train(
        self,
        env: MultiAgentEnvironment,
        config: TrainingConfig,
    ) -> TrainingResult:
        """
        Full training loop.
        """
        logger.info("Starting training: %s for %d episodes", config.algorithm.value, config.n_episodes)
        
        start_time = time.time()
        self._is_training = True
        
        # Initialize algorithm if needed
        if self._active_algorithm is None or self._algorithm_type != config.algorithm:
            self.initialize_algorithm(
                config.algorithm,
                config.n_agents,
                config.state_dim,
                config.action_dim,
                config.global_state_dim,
            )
        
        # Reset tracking
        self._reward_history = []
        self._loss_history = []
        self._best_reward = float('-inf')
        self._current_episode = 0
        self._total_steps = 0
        
        no_improvement_count = 0
        
        for episode in range(config.n_episodes):
            reward, update_info = self.train_episode(env, config.max_steps_per_episode)
            
            # Track loss
            if "critic_loss" in update_info:
                self._loss_history.append(update_info["critic_loss"])
            elif "loss" in update_info:
                self._loss_history.append(update_info["loss"])
            
            # Logging
            if (episode + 1) % 10 == 0:
                avg_reward = np.mean(self._reward_history[-10:])
                logger.info(
                    "Episode %d: reward=%.2f, avg_reward=%.2f, best=%.2f",
                    episode + 1, reward, avg_reward, self._best_reward
                )
            
            # Evaluation
            if (episode + 1) % config.eval_interval == 0:
                eval_result = self.evaluate(env, n_episodes=5)
                logger.info("Evaluation: mean_reward=%.2f", eval_result["mean_reward"])
            
            # Early stopping
            if reward >= config.target_reward:
                logger.info("Target reward reached!")
                break
            
            if reward <= self._best_reward:
                no_improvement_count += 1
                if no_improvement_count >= config.patience:
                    logger.info("Early stopping: no improvement for %d episodes", config.patience)
                    break
            else:
                no_improvement_count = 0
        
        self._is_training = False
        training_time = time.time() - start_time
        
        # Create result
        result = TrainingResult(
            algorithm=config.algorithm.value,
            n_episodes=self._current_episode,
            total_steps=self._total_steps,
            final_reward=self._reward_history[-1] if self._reward_history else 0,
            best_reward=self._best_reward,
            avg_reward=np.mean(self._reward_history) if self._reward_history else 0,
            training_time_seconds=training_time,
            reward_history=self._reward_history.copy(),
            loss_history=self._loss_history.copy(),
        )
        
        self._training_results.append(result)
        
        logger.info(
            "Training complete: %d episodes, best_reward=%.2f, time=%.1fs",
            result.n_episodes, result.best_reward, result.training_time_seconds
        )
        
        return result
    
    def get_algorithm(self) -> Optional[Any]:
        """Get active algorithm."""
        return self._active_algorithm
    
    def get_status(self) -> Dict[str, Any]:
        """Get coordinator status."""
        return {
            "algorithm": self._algorithm_type.value if self._algorithm_type else None,
            "is_training": self._is_training,
            "current_episode": self._current_episode,
            "total_steps": self._total_steps,
            "best_reward": round(self._best_reward, 4) if self._best_reward != float('-inf') else None,
            "recent_avg_reward": round(np.mean(self._reward_history[-10:]), 4) if self._reward_history else None,
            "training_runs": len(self._training_results),
        }
    
    def get_training_history(self) -> List[Dict[str, Any]]:
        """Get training history."""
        return [r.to_dict() for r in self._training_results]


# Singleton instance
_marl_coordinator: Optional[MARLCoordinator] = None


def get_marl_coordinator() -> MARLCoordinator:
    """Get the singleton MARL coordinator."""
    global _marl_coordinator
    if _marl_coordinator is None:
        _marl_coordinator = MARLCoordinator()
    return _marl_coordinator
