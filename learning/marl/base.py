"""
MERID MARL Base Classes

Foundation classes for Multi-Agent Reinforcement Learning.
"""

from __future__ import annotations

import time
import math
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple, Callable, Union
import numpy as np
from collections import deque

from utils.logger import get_logger

logger = get_logger("learning.marl.base")


class AgentRole(Enum):
    """Roles agents can play in MARL."""
    ACTOR = "actor"
    CRITIC = "critic"
    COORDINATOR = "coordinator"
    EXPLORER = "explorer"
    EXPLOITER = "exploiter"


@dataclass
class Experience:
    """A single experience tuple."""
    state: np.ndarray
    action: Union[int, np.ndarray]
    reward: float
    next_state: np.ndarray
    done: bool
    
    # Multi-agent specific
    agent_id: str = ""
    global_state: Optional[np.ndarray] = None
    other_actions: Optional[Dict[str, Any]] = None
    
    # Metadata
    timestamp: float = field(default_factory=time.time)
    info: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "action": self.action if isinstance(self.action, int) else self.action.tolist(),
            "reward": round(self.reward, 6),
            "done": self.done,
            "timestamp": self.timestamp,
        }


@dataclass
class Trajectory:
    """A sequence of experiences forming a trajectory."""
    agent_id: str
    experiences: List[Experience] = field(default_factory=list)
    
    # Computed values
    total_reward: float = 0.0
    length: int = 0
    
    # Value estimates
    returns: Optional[np.ndarray] = None
    advantages: Optional[np.ndarray] = None
    values: Optional[np.ndarray] = None
    
    def add(self, experience: Experience) -> None:
        """Add experience to trajectory."""
        self.experiences.append(experience)
        self.total_reward += experience.reward
        self.length += 1
    
    def compute_returns(self, gamma: float = 0.99) -> np.ndarray:
        """Compute discounted returns."""
        rewards = [e.reward for e in self.experiences]
        returns = np.zeros(len(rewards))
        
        running_return = 0.0
        for t in reversed(range(len(rewards))):
            running_return = rewards[t] + gamma * running_return
            returns[t] = running_return
        
        self.returns = returns
        return returns
    
    def compute_gae(
        self,
        values: np.ndarray,
        gamma: float = 0.99,
        gae_lambda: float = 0.95,
    ) -> np.ndarray:
        """Compute Generalized Advantage Estimation."""
        rewards = np.array([e.reward for e in self.experiences])
        dones = np.array([e.done for e in self.experiences])
        
        # Append bootstrap value
        if len(values) == len(rewards):
            next_values = np.append(values[1:], 0.0)
        else:
            next_values = values[1:]
        
        # TD errors
        deltas = rewards + gamma * next_values * (1 - dones) - values[:len(rewards)]
        
        # GAE
        advantages = np.zeros_like(rewards)
        running_advantage = 0.0
        
        for t in reversed(range(len(rewards))):
            running_advantage = deltas[t] + gamma * gae_lambda * (1 - dones[t]) * running_advantage
            advantages[t] = running_advantage
        
        self.advantages = advantages
        self.values = values[:len(rewards)]
        self.returns = advantages + self.values
        
        return advantages
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "length": self.length,
            "total_reward": round(self.total_reward, 4),
        }


class ReplayBuffer:
    """Experience replay buffer for off-policy learning."""
    
    def __init__(self, capacity: int = 100000):
        self.capacity = capacity
        self._buffer: deque = deque(maxlen=capacity)
        self._priorities: Optional[np.ndarray] = None
        
    def add(self, experience: Experience) -> None:
        """Add experience to buffer."""
        self._buffer.append(experience)
    
    def add_trajectory(self, trajectory: Trajectory) -> None:
        """Add all experiences from trajectory."""
        for exp in trajectory.experiences:
            self.add(exp)
    
    def sample(self, batch_size: int) -> List[Experience]:
        """Sample random batch."""
        indices = np.random.choice(len(self._buffer), min(batch_size, len(self._buffer)), replace=False)
        return [self._buffer[i] for i in indices]
    
    def sample_by_agent(self, agent_id: str, batch_size: int) -> List[Experience]:
        """Sample experiences for specific agent."""
        agent_experiences = [e for e in self._buffer if e.agent_id == agent_id]
        if not agent_experiences:
            return []
        indices = np.random.choice(len(agent_experiences), min(batch_size, len(agent_experiences)), replace=False)
        return [agent_experiences[i] for i in indices]
    
    def __len__(self) -> int:
        return len(self._buffer)
    
    def clear(self) -> None:
        self._buffer.clear()


class MARLPolicy(ABC):
    """Abstract base class for MARL policies."""
    
    def __init__(
        self,
        state_dim: int,
        action_dim: int,
        hidden_dims: List[int] = None,
    ):
        self.state_dim = state_dim
        self.action_dim = action_dim
        self.hidden_dims = hidden_dims or [256, 256]
        
        # Parameters (to be implemented by subclasses)
        self._parameters: Dict[str, np.ndarray] = {}
        
    @abstractmethod
    def forward(self, state: np.ndarray) -> np.ndarray:
        """Forward pass through policy network."""
        pass
    
    @abstractmethod
    def get_action(self, state: np.ndarray, deterministic: bool = False) -> Tuple[Any, float]:
        """Get action and log probability."""
        pass
    
    @abstractmethod
    def get_log_prob(self, state: np.ndarray, action: Any) -> float:
        """Get log probability of action given state."""
        pass
    
    def get_parameters(self) -> Dict[str, np.ndarray]:
        """Get policy parameters."""
        return self._parameters.copy()
    
    def set_parameters(self, parameters: Dict[str, np.ndarray]) -> None:
        """Set policy parameters."""
        self._parameters = parameters.copy()


class MARLCritic(ABC):
    """Abstract base class for MARL critics."""
    
    def __init__(
        self,
        state_dim: int,
        action_dim: int = 0,
        n_agents: int = 1,
        hidden_dims: List[int] = None,
    ):
        self.state_dim = state_dim
        self.action_dim = action_dim
        self.n_agents = n_agents
        self.hidden_dims = hidden_dims or [256, 256]
        
        self._parameters: Dict[str, np.ndarray] = {}
    
    @abstractmethod
    def forward(
        self,
        state: np.ndarray,
        actions: Optional[np.ndarray] = None,
    ) -> np.ndarray:
        """Forward pass through critic network."""
        pass
    
    @abstractmethod
    def get_value(
        self,
        state: np.ndarray,
        actions: Optional[np.ndarray] = None,
    ) -> float:
        """Get value estimate."""
        pass


class MultiAgentEnvironment(ABC):
    """Abstract base class for multi-agent environments."""
    
    def __init__(self, n_agents: int):
        self.n_agents = n_agents
        self._agent_ids: List[str] = [f"agent_{i}" for i in range(n_agents)]
        
    @property
    def agent_ids(self) -> List[str]:
        return self._agent_ids
    
    @abstractmethod
    def reset(self) -> Dict[str, np.ndarray]:
        """Reset environment and return initial observations."""
        pass
    
    @abstractmethod
    def step(
        self,
        actions: Dict[str, Any],
    ) -> Tuple[Dict[str, np.ndarray], Dict[str, float], Dict[str, bool], Dict[str, Any]]:
        """
        Execute actions and return (observations, rewards, dones, infos).
        """
        pass
    
    @abstractmethod
    def get_global_state(self) -> np.ndarray:
        """Get global state for centralized training."""
        pass
    
    def get_observation_space(self, agent_id: str) -> Tuple[int, ...]:
        """Get observation space shape for agent."""
        # Default observation space for Phase 0
        # Returns a tuple representing the observation dimensions
        # Format: (market_features, agent_state, global_state, history_length)
        return (10, 8, 6, 20)  # (market_data, agent_state, global_state, history)
    
    def get_action_space(self, agent_id: str) -> int:
        """Get action space size for agent."""
        # Default action space for Phase 0
        # Returns the number of possible actions
        # Actions: 0=hold, 1=buy, 2=sell, 3=stake, 4=unstake
        return 5


class MARLAgent:
    """
    Base MARL agent that can be extended for specific algorithms.
    """
    
    def __init__(
        self,
        agent_id: str,
        state_dim: int,
        action_dim: int,
        role: AgentRole = AgentRole.ACTOR,
    ):
        self.agent_id = agent_id
        self.state_dim = state_dim
        self.action_dim = action_dim
        self.role = role
        
        # Policy and critic (to be set by algorithm)
        self.policy: Optional[MARLPolicy] = None
        self.critic: Optional[MARLCritic] = None
        
        # Experience collection
        self._current_trajectory: Optional[Trajectory] = None
        self._trajectories: List[Trajectory] = []
        
        # Statistics
        self._total_steps = 0
        self._total_episodes = 0
        self._total_reward = 0.0
        
        logger.info("MARL agent initialized: %s (role=%s)", agent_id, role.value)
    
    def start_episode(self) -> None:
        """Start a new episode."""
        self._current_trajectory = Trajectory(agent_id=self.agent_id)
    
    def record_experience(self, experience: Experience) -> None:
        """Record an experience."""
        experience.agent_id = self.agent_id
        
        if self._current_trajectory is None:
            self.start_episode()
        
        self._current_trajectory.add(experience)
        self._total_steps += 1
        self._total_reward += experience.reward
    
    def end_episode(self) -> Trajectory:
        """End current episode and return trajectory."""
        if self._current_trajectory is None:
            return Trajectory(agent_id=self.agent_id)
        
        trajectory = self._current_trajectory
        self._trajectories.append(trajectory)
        self._current_trajectory = None
        self._total_episodes += 1
        
        return trajectory
    
    def get_action(self, state: np.ndarray, deterministic: bool = False) -> Tuple[Any, float]:
        """Get action from policy."""
        if self.policy is None:
            # Random action
            action = np.random.randint(0, self.action_dim)
            return action, -np.log(1.0 / self.action_dim)
        
        return self.policy.get_action(state, deterministic)
    
    def get_value(self, state: np.ndarray) -> float:
        """Get value estimate from critic."""
        if self.critic is None:
            return 0.0
        return self.critic.get_value(state)
    
    def get_recent_trajectories(self, n: int = 10) -> List[Trajectory]:
        """Get recent trajectories."""
        return self._trajectories[-n:]
    
    def clear_trajectories(self) -> None:
        """Clear stored trajectories."""
        self._trajectories.clear()
    
    def get_stats(self) -> Dict[str, Any]:
        """Get agent statistics."""
        return {
            "agent_id": self.agent_id,
            "role": self.role.value,
            "total_steps": self._total_steps,
            "total_episodes": self._total_episodes,
            "total_reward": round(self._total_reward, 4),
            "avg_reward_per_episode": round(
                self._total_reward / max(1, self._total_episodes), 4
            ),
        }


class NeuralNetwork:
    """
    Simple neural network implementation using NumPy.
    
    For production, this would be replaced with PyTorch/JAX.
    """
    
    def __init__(
        self,
        input_dim: int,
        output_dim: int,
        hidden_dims: List[int] = None,
        activation: str = "relu",
    ):
        self.input_dim = input_dim
        self.output_dim = output_dim
        self.hidden_dims = hidden_dims or [256, 256]
        self.activation = activation
        
        # Initialize weights
        self.weights: List[np.ndarray] = []
        self.biases: List[np.ndarray] = []
        
        dims = [input_dim] + self.hidden_dims + [output_dim]
        
        for i in range(len(dims) - 1):
            # Xavier initialization
            scale = np.sqrt(2.0 / (dims[i] + dims[i+1]))
            self.weights.append(np.random.randn(dims[i], dims[i+1]) * scale)
            self.biases.append(np.zeros(dims[i+1]))
    
    def _activate(self, x: np.ndarray, final: bool = False) -> np.ndarray:
        """Apply activation function."""
        if final:
            return x  # Linear output
        
        if self.activation == "relu":
            return np.maximum(0, x)
        elif self.activation == "tanh":
            return np.tanh(x)
        elif self.activation == "sigmoid":
            return 1 / (1 + np.exp(-np.clip(x, -500, 500)))
        return x
    
    def forward(self, x: np.ndarray) -> np.ndarray:
        """Forward pass."""
        for i, (w, b) in enumerate(zip(self.weights, self.biases)):
            x = x @ w + b
            x = self._activate(x, final=(i == len(self.weights) - 1))
        return x
    
    def get_parameters(self) -> Dict[str, np.ndarray]:
        """Get all parameters."""
        params = {}
        for i, (w, b) in enumerate(zip(self.weights, self.biases)):
            params[f"w{i}"] = w.copy()
            params[f"b{i}"] = b.copy()
        return params
    
    def set_parameters(self, params: Dict[str, np.ndarray]) -> None:
        """Set all parameters."""
        for i in range(len(self.weights)):
            if f"w{i}" in params:
                self.weights[i] = params[f"w{i}"].copy()
            if f"b{i}" in params:
                self.biases[i] = params[f"b{i}"].copy()


class CategoricalPolicy(MARLPolicy):
    """Categorical policy for discrete action spaces."""
    
    def __init__(
        self,
        state_dim: int,
        action_dim: int,
        hidden_dims: List[int] = None,
    ):
        super().__init__(state_dim, action_dim, hidden_dims)
        
        self.network = NeuralNetwork(
            state_dim, action_dim, hidden_dims, activation="relu"
        )
    
    def forward(self, state: np.ndarray) -> np.ndarray:
        """Get action logits."""
        return self.network.forward(state)
    
    def get_action(self, state: np.ndarray, deterministic: bool = False) -> Tuple[int, float]:
        """Sample action from policy."""
        logits = self.forward(state)
        
        # Softmax
        exp_logits = np.exp(logits - np.max(logits))
        probs = exp_logits / exp_logits.sum()
        
        if deterministic:
            action = int(np.argmax(probs))
        else:
            action = int(np.random.choice(self.action_dim, p=probs))
        
        log_prob = np.log(probs[action] + 1e-10)
        
        return action, float(log_prob)
    
    def get_log_prob(self, state: np.ndarray, action: int) -> float:
        """Get log probability of action."""
        logits = self.forward(state)
        exp_logits = np.exp(logits - np.max(logits))
        probs = exp_logits / exp_logits.sum()
        return float(np.log(probs[action] + 1e-10))
    
    def get_entropy(self, state: np.ndarray) -> float:
        """Get entropy of action distribution."""
        logits = self.forward(state)
        exp_logits = np.exp(logits - np.max(logits))
        probs = exp_logits / exp_logits.sum()
        return float(-np.sum(probs * np.log(probs + 1e-10)))
    
    def get_parameters(self) -> Dict[str, np.ndarray]:
        return self.network.get_parameters()
    
    def set_parameters(self, parameters: Dict[str, np.ndarray]) -> None:
        self.network.set_parameters(parameters)


class ValueCritic(MARLCritic):
    """Value function critic (V(s))."""
    
    def __init__(
        self,
        state_dim: int,
        hidden_dims: List[int] = None,
    ):
        super().__init__(state_dim, 0, 1, hidden_dims)
        
        self.network = NeuralNetwork(
            state_dim, 1, hidden_dims, activation="relu"
        )
    
    def forward(self, state: np.ndarray, actions: Optional[np.ndarray] = None) -> np.ndarray:
        """Get value estimate."""
        return self.network.forward(state)
    
    def get_value(self, state: np.ndarray, actions: Optional[np.ndarray] = None) -> float:
        """Get scalar value."""
        return float(self.forward(state)[0])
    
    def get_parameters(self) -> Dict[str, np.ndarray]:
        return self.network.get_parameters()
    
    def set_parameters(self, parameters: Dict[str, np.ndarray]) -> None:
        self.network.set_parameters(parameters)


class QCritic(MARLCritic):
    """Q-function critic (Q(s, a))."""
    
    def __init__(
        self,
        state_dim: int,
        action_dim: int,
        hidden_dims: List[int] = None,
    ):
        super().__init__(state_dim, action_dim, 1, hidden_dims)
        
        # Output Q-value for each action
        self.network = NeuralNetwork(
            state_dim, action_dim, hidden_dims, activation="relu"
        )
    
    def forward(self, state: np.ndarray, actions: Optional[np.ndarray] = None) -> np.ndarray:
        """Get Q-values for all actions."""
        return self.network.forward(state)
    
    def get_value(self, state: np.ndarray, actions: Optional[np.ndarray] = None) -> float:
        """Get Q-value for specific action or max Q-value."""
        q_values = self.forward(state)
        
        if actions is not None:
            action = int(actions[0]) if isinstance(actions, np.ndarray) else int(actions)
            return float(q_values[action])
        
        return float(np.max(q_values))
    
    def get_parameters(self) -> Dict[str, np.ndarray]:
        return self.network.get_parameters()
    
    def set_parameters(self, parameters: Dict[str, np.ndarray]) -> None:
        self.network.set_parameters(parameters)
