"""
MERID MARL - Multi-Agent Proximal Policy Optimization (MAPPO)

MAPPO extends PPO to multi-agent settings with:
- Centralized training with decentralized execution (CTDE)
- Shared critic with global state
- Per-agent policy networks
- Clipped surrogate objective

Reference: Yu et al., "The Surprising Effectiveness of PPO in Cooperative Multi-Agent Games"
"""

from __future__ import annotations

import time
import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple
import numpy as np

from learning.marl.base import (
    MARLAgent,
    MARLPolicy,
    MARLCritic,
    Trajectory,
    Experience,
    CategoricalPolicy,
    ValueCritic,
    NeuralNetwork,
    AgentRole,
)
from utils.logger import get_logger

logger = get_logger("learning.marl.mappo")


@dataclass
class MAPPOConfig:
    """Configuration for MAPPO algorithm."""
    # Learning rates
    policy_lr: float = 3e-4
    critic_lr: float = 1e-3
    
    # PPO hyperparameters
    clip_epsilon: float = 0.2
    entropy_coef: float = 0.01
    value_coef: float = 0.5
    max_grad_norm: float = 0.5
    
    # GAE
    gamma: float = 0.99
    gae_lambda: float = 0.95
    
    # Training
    n_epochs: int = 10
    batch_size: int = 64
    n_minibatches: int = 4
    
    # Architecture
    hidden_dims: List[int] = field(default_factory=lambda: [256, 256])
    
    # Shared parameters
    share_policy: bool = False
    share_critic: bool = True
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "policy_lr": self.policy_lr,
            "critic_lr": self.critic_lr,
            "clip_epsilon": self.clip_epsilon,
            "entropy_coef": self.entropy_coef,
            "gamma": self.gamma,
            "gae_lambda": self.gae_lambda,
            "n_epochs": self.n_epochs,
            "batch_size": self.batch_size,
        }


class CentralizedCritic(MARLCritic):
    """
    Centralized critic that takes global state as input.
    
    Used for CTDE (Centralized Training, Decentralized Execution).
    """
    
    def __init__(
        self,
        global_state_dim: int,
        n_agents: int,
        hidden_dims: List[int] = None,
    ):
        super().__init__(global_state_dim, 0, n_agents, hidden_dims)
        
        self.global_state_dim = global_state_dim
        
        # Single value output
        self.network = NeuralNetwork(
            global_state_dim, 1, hidden_dims, activation="relu"
        )
    
    def forward(self, state: np.ndarray, actions: Optional[np.ndarray] = None) -> np.ndarray:
        """Get value from global state."""
        return self.network.forward(state)
    
    def get_value(self, state: np.ndarray, actions: Optional[np.ndarray] = None) -> float:
        """Get scalar value."""
        return float(self.forward(state)[0])
    
    def get_parameters(self) -> Dict[str, np.ndarray]:
        return self.network.get_parameters()
    
    def set_parameters(self, parameters: Dict[str, np.ndarray]) -> None:
        self.network.set_parameters(parameters)


class MAPPOAgent(MARLAgent):
    """MAPPO agent with policy and access to centralized critic."""
    
    def __init__(
        self,
        agent_id: str,
        state_dim: int,
        action_dim: int,
        config: MAPPOConfig,
    ):
        super().__init__(agent_id, state_dim, action_dim, AgentRole.ACTOR)
        
        self.config = config
        
        # Initialize policy
        self.policy = CategoricalPolicy(
            state_dim, action_dim, config.hidden_dims
        )
        
        # Old policy for importance sampling
        self._old_policy_params: Optional[Dict[str, np.ndarray]] = None
        
        # Training statistics
        self._policy_losses: List[float] = []
        self._entropy_losses: List[float] = []
    
    def save_old_policy(self) -> None:
        """Save current policy parameters for importance sampling."""
        self._old_policy_params = self.policy.get_parameters()
    
    def get_old_log_prob(self, state: np.ndarray, action: int) -> float:
        """Get log probability under old policy."""
        if self._old_policy_params is None:
            return self.policy.get_log_prob(state, action)
        
        # Temporarily swap parameters
        current_params = self.policy.get_parameters()
        self.policy.set_parameters(self._old_policy_params)
        
        log_prob = self.policy.get_log_prob(state, action)
        
        # Restore current parameters
        self.policy.set_parameters(current_params)
        
        return log_prob
    
    def compute_policy_loss(
        self,
        states: np.ndarray,
        actions: np.ndarray,
        advantages: np.ndarray,
        old_log_probs: np.ndarray,
    ) -> Tuple[float, float]:
        """
        Compute clipped PPO policy loss.
        
        Returns (policy_loss, entropy_loss).
        """
        policy_loss = 0.0
        entropy_loss = 0.0
        
        for i in range(len(states)):
            state = states[i]
            action = int(actions[i])
            advantage = advantages[i]
            old_log_prob = old_log_probs[i]
            
            # Current log probability
            new_log_prob = self.policy.get_log_prob(state, action)
            
            # Importance ratio
            ratio = np.exp(new_log_prob - old_log_prob)
            
            # Clipped surrogate objective
            surr1 = ratio * advantage
            surr2 = np.clip(ratio, 1 - self.config.clip_epsilon, 1 + self.config.clip_epsilon) * advantage
            
            policy_loss -= min(surr1, surr2)
            
            # Entropy bonus
            entropy = self.policy.get_entropy(state)
            entropy_loss -= entropy
        
        n = len(states)
        return policy_loss / n, entropy_loss / n
    
    def update_policy(
        self,
        states: np.ndarray,
        actions: np.ndarray,
        advantages: np.ndarray,
        old_log_probs: np.ndarray,
    ) -> Dict[str, float]:
        """
        Update policy using PPO objective.
        
        Note: In production, this would use automatic differentiation.
        Here we use numerical gradients for demonstration.
        """
        policy_loss, entropy_loss = self.compute_policy_loss(
            states, actions, advantages, old_log_probs
        )
        
        total_loss = policy_loss + self.config.entropy_coef * entropy_loss
        
        # Numerical gradient update (simplified)
        params = self.policy.get_parameters()
        epsilon = 1e-4
        
        for key in params:
            grad = np.zeros_like(params[key])
            
            # Sample gradient directions for efficiency
            n_samples = min(10, params[key].size)
            indices = np.random.choice(params[key].size, n_samples, replace=False)
            
            for idx in indices:
                flat_idx = np.unravel_index(idx, params[key].shape)
                
                # Positive perturbation
                params[key][flat_idx] += epsilon
                self.policy.set_parameters(params)
                loss_plus, _ = self.compute_policy_loss(states, actions, advantages, old_log_probs)
                
                # Negative perturbation
                params[key][flat_idx] -= 2 * epsilon
                self.policy.set_parameters(params)
                loss_minus, _ = self.compute_policy_loss(states, actions, advantages, old_log_probs)
                
                # Restore
                params[key][flat_idx] += epsilon
                
                # Gradient estimate
                grad[flat_idx] = (loss_plus - loss_minus) / (2 * epsilon)
            
            # Update with gradient descent
            params[key] -= self.config.policy_lr * grad
        
        self.policy.set_parameters(params)
        
        self._policy_losses.append(policy_loss)
        self._entropy_losses.append(entropy_loss)
        
        return {
            "policy_loss": policy_loss,
            "entropy_loss": entropy_loss,
            "total_loss": total_loss,
        }


class MAPPO:
    """
    Multi-Agent Proximal Policy Optimization.
    
    Implements CTDE with:
    - Per-agent policies (decentralized execution)
    - Centralized critic (centralized training)
    - PPO clipped objective
    - GAE for advantage estimation
    """
    
    def __init__(
        self,
        n_agents: int,
        state_dim: int,
        action_dim: int,
        global_state_dim: int,
        config: Optional[MAPPOConfig] = None,
    ):
        self.n_agents = n_agents
        self.state_dim = state_dim
        self.action_dim = action_dim
        self.global_state_dim = global_state_dim
        self.config = config or MAPPOConfig()
        
        # Initialize agents
        self.agents: Dict[str, MAPPOAgent] = {}
        for i in range(n_agents):
            agent_id = f"mappo_agent_{i}"
            self.agents[agent_id] = MAPPOAgent(
                agent_id, state_dim, action_dim, self.config
            )
        
        # Centralized critic (shared)
        self.critic = CentralizedCritic(
            global_state_dim, n_agents, self.config.hidden_dims
        )
        
        # Training statistics
        self._update_count = 0
        self._critic_losses: List[float] = []
        
        logger.info(
            "MAPPO initialized: %d agents, state_dim=%d, action_dim=%d",
            n_agents, state_dim, action_dim
        )
    
    def get_actions(
        self,
        observations: Dict[str, np.ndarray],
        deterministic: bool = False,
    ) -> Dict[str, Tuple[int, float]]:
        """Get actions for all agents."""
        actions = {}
        for agent_id, obs in observations.items():
            if agent_id in self.agents:
                actions[agent_id] = self.agents[agent_id].get_action(obs, deterministic)
        return actions
    
    def get_value(self, global_state: np.ndarray) -> float:
        """Get value estimate from centralized critic."""
        return self.critic.get_value(global_state)
    
    def collect_trajectories(
        self,
        trajectories: Dict[str, Trajectory],
        global_states: List[np.ndarray],
    ) -> Dict[str, Dict[str, np.ndarray]]:
        """
        Process trajectories and compute advantages.
        
        Returns processed data for each agent.
        """
        processed = {}
        
        for agent_id, trajectory in trajectories.items():
            if agent_id not in self.agents:
                continue
            
            agent = self.agents[agent_id]
            
            # Get states, actions, rewards
            states = np.array([e.state for e in trajectory.experiences])
            actions = np.array([e.action for e in trajectory.experiences])
            rewards = np.array([e.reward for e in trajectory.experiences])
            
            # Get value estimates
            values = np.array([
                self.critic.get_value(gs) for gs in global_states[:len(trajectory.experiences)]
            ])
            
            # Compute GAE
            advantages = trajectory.compute_gae(
                values, self.config.gamma, self.config.gae_lambda
            )
            
            # Get old log probs
            agent.save_old_policy()
            old_log_probs = np.array([
                agent.get_old_log_prob(states[i], int(actions[i]))
                for i in range(len(states))
            ])
            
            # Normalize advantages
            advantages = (advantages - advantages.mean()) / (advantages.std() + 1e-8)
            
            processed[agent_id] = {
                "states": states,
                "actions": actions,
                "rewards": rewards,
                "values": values,
                "advantages": advantages,
                "returns": trajectory.returns,
                "old_log_probs": old_log_probs,
            }
        
        return processed
    
    def update(
        self,
        processed_data: Dict[str, Dict[str, np.ndarray]],
        global_states: np.ndarray,
    ) -> Dict[str, Any]:
        """
        Update all agents and critic.
        """
        self._update_count += 1
        
        results = {
            "update_count": self._update_count,
            "agent_losses": {},
            "critic_loss": 0.0,
        }
        
        # Update each agent's policy
        for agent_id, data in processed_data.items():
            agent = self.agents[agent_id]
            
            for epoch in range(self.config.n_epochs):
                # Mini-batch updates
                n_samples = len(data["states"])
                indices = np.random.permutation(n_samples)
                
                for start in range(0, n_samples, self.config.batch_size):
                    end = min(start + self.config.batch_size, n_samples)
                    batch_indices = indices[start:end]
                    
                    batch_states = data["states"][batch_indices]
                    batch_actions = data["actions"][batch_indices]
                    batch_advantages = data["advantages"][batch_indices]
                    batch_old_log_probs = data["old_log_probs"][batch_indices]
                    
                    loss_info = agent.update_policy(
                        batch_states,
                        batch_actions,
                        batch_advantages,
                        batch_old_log_probs,
                    )
            
            results["agent_losses"][agent_id] = loss_info
        
        # Update centralized critic
        critic_loss = self._update_critic(processed_data, global_states)
        results["critic_loss"] = critic_loss
        self._critic_losses.append(critic_loss)
        
        return results
    
    def _update_critic(
        self,
        processed_data: Dict[str, Dict[str, np.ndarray]],
        global_states: np.ndarray,
    ) -> float:
        """Update centralized critic."""
        # Aggregate returns from all agents
        all_returns = []
        all_global_states = []
        
        for agent_id, data in processed_data.items():
            returns = data["returns"]
            n = len(returns)
            
            all_returns.extend(returns)
            all_global_states.extend(global_states[:n])
        
        if not all_returns:
            return 0.0
        
        all_returns = np.array(all_returns)
        all_global_states = np.array(all_global_states)
        
        # Compute MSE loss
        predictions = np.array([self.critic.get_value(gs) for gs in all_global_states])
        loss = np.mean((predictions - all_returns) ** 2)
        
        # Numerical gradient update for critic
        params = self.critic.get_parameters()
        epsilon = 1e-4
        
        for key in params:
            grad = np.zeros_like(params[key])
            n_samples = min(10, params[key].size)
            indices = np.random.choice(params[key].size, n_samples, replace=False)
            
            for idx in indices:
                flat_idx = np.unravel_index(idx, params[key].shape)
                
                params[key][flat_idx] += epsilon
                self.critic.set_parameters(params)
                preds_plus = np.array([self.critic.get_value(gs) for gs in all_global_states])
                loss_plus = np.mean((preds_plus - all_returns) ** 2)
                
                params[key][flat_idx] -= 2 * epsilon
                self.critic.set_parameters(params)
                preds_minus = np.array([self.critic.get_value(gs) for gs in all_global_states])
                loss_minus = np.mean((preds_minus - all_returns) ** 2)
                
                params[key][flat_idx] += epsilon
                grad[flat_idx] = (loss_plus - loss_minus) / (2 * epsilon)
            
            params[key] -= self.config.critic_lr * grad
        
        self.critic.set_parameters(params)
        
        return float(loss)
    
    def save(self, path: str) -> None:
        """Save model parameters."""
        data = {
            "config": self.config.to_dict(),
            "critic": self.critic.get_parameters(),
            "agents": {
                agent_id: agent.policy.get_parameters()
                for agent_id, agent in self.agents.items()
            },
        }
        np.save(path, data, allow_pickle=True)
        logger.info("MAPPO saved to %s", path)
    
    def load(self, path: str) -> None:
        """Load model parameters."""
        data = np.load(path, allow_pickle=True).item()
        
        self.critic.set_parameters(data["critic"])
        for agent_id, params in data["agents"].items():
            if agent_id in self.agents:
                self.agents[agent_id].policy.set_parameters(params)
        
        logger.info("MAPPO loaded from %s", path)
    
    def get_stats(self) -> Dict[str, Any]:
        """Get training statistics."""
        return {
            "n_agents": self.n_agents,
            "update_count": self._update_count,
            "avg_critic_loss": np.mean(self._critic_losses[-100:]) if self._critic_losses else 0,
            "agent_stats": {
                agent_id: agent.get_stats()
                for agent_id, agent in self.agents.items()
            },
        }
