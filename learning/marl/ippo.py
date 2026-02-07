"""
MERID MARL - Independent Proximal Policy Optimization (IPPO)

IPPO applies PPO independently to each agent:
- Each agent has its own policy and value function
- No centralized critic or communication
- Simple but effective baseline for many tasks

Reference: de Witt et al., "Is Independent Learning All You Need in the StarCraft Multi-Agent Challenge?"
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple
import numpy as np

from learning.marl.base import (
    MARLAgent,
    Trajectory,
    Experience,
    CategoricalPolicy,
    ValueCritic,
    AgentRole,
)
from utils.logger import get_logger

logger = get_logger("learning.marl.ippo")


@dataclass
class IPPOConfig:
    """Configuration for IPPO algorithm."""
    # Learning rates
    policy_lr: float = 3e-4
    value_lr: float = 1e-3
    
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
    
    # Architecture
    hidden_dims: List[int] = field(default_factory=lambda: [256, 256])
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "policy_lr": self.policy_lr,
            "value_lr": self.value_lr,
            "clip_epsilon": self.clip_epsilon,
            "entropy_coef": self.entropy_coef,
            "gamma": self.gamma,
            "gae_lambda": self.gae_lambda,
            "n_epochs": self.n_epochs,
        }


class IPPOAgent(MARLAgent):
    """IPPO agent with independent policy and value function."""
    
    def __init__(
        self,
        agent_id: str,
        state_dim: int,
        action_dim: int,
        config: IPPOConfig,
    ):
        super().__init__(agent_id, state_dim, action_dim, AgentRole.ACTOR)
        
        self.config = config
        
        # Initialize policy
        self.policy = CategoricalPolicy(
            state_dim, action_dim, config.hidden_dims
        )
        
        # Initialize value function (independent)
        self.value_fn = ValueCritic(state_dim, config.hidden_dims)
        
        # Old policy for importance sampling
        self._old_policy_params: Optional[Dict[str, np.ndarray]] = None
        
        # Training statistics
        self._policy_losses: List[float] = []
        self._value_losses: List[float] = []
    
    def get_value(self, state: np.ndarray) -> float:
        """Get value estimate."""
        return self.value_fn.get_value(state)
    
    def save_old_policy(self) -> None:
        """Save current policy parameters."""
        self._old_policy_params = self.policy.get_parameters()
    
    def get_old_log_prob(self, state: np.ndarray, action: int) -> float:
        """Get log probability under old policy."""
        if self._old_policy_params is None:
            return self.policy.get_log_prob(state, action)
        
        current_params = self.policy.get_parameters()
        self.policy.set_parameters(self._old_policy_params)
        log_prob = self.policy.get_log_prob(state, action)
        self.policy.set_parameters(current_params)
        
        return log_prob
    
    def update(
        self,
        states: np.ndarray,
        actions: np.ndarray,
        returns: np.ndarray,
        advantages: np.ndarray,
        old_log_probs: np.ndarray,
    ) -> Dict[str, float]:
        """Update policy and value function."""
        # Update policy
        policy_loss = self._update_policy(states, actions, advantages, old_log_probs)
        
        # Update value function
        value_loss = self._update_value(states, returns)
        
        self._policy_losses.append(policy_loss)
        self._value_losses.append(value_loss)
        
        return {
            "policy_loss": policy_loss,
            "value_loss": value_loss,
        }
    
    def _update_policy(
        self,
        states: np.ndarray,
        actions: np.ndarray,
        advantages: np.ndarray,
        old_log_probs: np.ndarray,
    ) -> float:
        """Update policy using clipped PPO objective."""
        policy_loss = 0.0
        entropy_loss = 0.0
        
        for i in range(len(states)):
            state = states[i]
            action = int(actions[i])
            advantage = advantages[i]
            old_log_prob = old_log_probs[i]
            
            new_log_prob = self.policy.get_log_prob(state, action)
            ratio = np.exp(new_log_prob - old_log_prob)
            
            surr1 = ratio * advantage
            surr2 = np.clip(ratio, 1 - self.config.clip_epsilon, 1 + self.config.clip_epsilon) * advantage
            
            policy_loss -= min(surr1, surr2)
            entropy_loss -= self.policy.get_entropy(state)
        
        n = len(states)
        policy_loss /= n
        entropy_loss /= n
        
        total_loss = policy_loss + self.config.entropy_coef * entropy_loss
        
        # Numerical gradient update
        params = self.policy.get_parameters()
        epsilon = 1e-4
        
        for key in params:
            grad = np.zeros_like(params[key])
            n_samples = min(10, params[key].size)
            indices = np.random.choice(params[key].size, n_samples, replace=False)
            
            for idx in indices:
                flat_idx = np.unravel_index(idx, params[key].shape)
                
                params[key][flat_idx] += epsilon
                self.policy.set_parameters(params)
                loss_plus = self._compute_policy_loss(states, actions, advantages, old_log_probs)
                
                params[key][flat_idx] -= 2 * epsilon
                self.policy.set_parameters(params)
                loss_minus = self._compute_policy_loss(states, actions, advantages, old_log_probs)
                
                params[key][flat_idx] += epsilon
                grad[flat_idx] = (loss_plus - loss_minus) / (2 * epsilon)
            
            params[key] -= self.config.policy_lr * grad
        
        self.policy.set_parameters(params)
        
        return total_loss
    
    def _compute_policy_loss(
        self,
        states: np.ndarray,
        actions: np.ndarray,
        advantages: np.ndarray,
        old_log_probs: np.ndarray,
    ) -> float:
        """Compute policy loss."""
        loss = 0.0
        for i in range(len(states)):
            new_log_prob = self.policy.get_log_prob(states[i], int(actions[i]))
            ratio = np.exp(new_log_prob - old_log_probs[i])
            surr1 = ratio * advantages[i]
            surr2 = np.clip(ratio, 1 - self.config.clip_epsilon, 1 + self.config.clip_epsilon) * advantages[i]
            loss -= min(surr1, surr2)
        return loss / len(states)
    
    def _update_value(
        self,
        states: np.ndarray,
        returns: np.ndarray,
    ) -> float:
        """Update value function using MSE loss."""
        # Compute current loss
        predictions = np.array([self.value_fn.get_value(s) for s in states])
        loss = np.mean((predictions - returns) ** 2)
        
        # Numerical gradient update
        params = self.value_fn.get_parameters()
        epsilon = 1e-4
        
        for key in params:
            grad = np.zeros_like(params[key])
            n_samples = min(10, params[key].size)
            indices = np.random.choice(params[key].size, n_samples, replace=False)
            
            for idx in indices:
                flat_idx = np.unravel_index(idx, params[key].shape)
                
                params[key][flat_idx] += epsilon
                self.value_fn.set_parameters(params)
                preds_plus = np.array([self.value_fn.get_value(s) for s in states])
                loss_plus = np.mean((preds_plus - returns) ** 2)
                
                params[key][flat_idx] -= 2 * epsilon
                self.value_fn.set_parameters(params)
                preds_minus = np.array([self.value_fn.get_value(s) for s in states])
                loss_minus = np.mean((preds_minus - returns) ** 2)
                
                params[key][flat_idx] += epsilon
                grad[flat_idx] = (loss_plus - loss_minus) / (2 * epsilon)
            
            params[key] -= self.config.value_lr * grad
        
        self.value_fn.set_parameters(params)
        
        return loss


class IPPO:
    """
    Independent Proximal Policy Optimization.
    
    Key features:
    - Each agent learns independently
    - No centralized critic or communication
    - Simple and scalable
    - Surprisingly effective baseline
    """
    
    def __init__(
        self,
        n_agents: int,
        state_dim: int,
        action_dim: int,
        config: Optional[IPPOConfig] = None,
    ):
        self.n_agents = n_agents
        self.state_dim = state_dim
        self.action_dim = action_dim
        self.config = config or IPPOConfig()
        
        # Initialize agents
        self.agents: Dict[str, IPPOAgent] = {}
        for i in range(n_agents):
            agent_id = f"ippo_agent_{i}"
            self.agents[agent_id] = IPPOAgent(
                agent_id, state_dim, action_dim, self.config
            )
        
        # Training statistics
        self._update_count = 0
        
        logger.info(
            "IPPO initialized: %d agents, state_dim=%d, action_dim=%d",
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
    
    def collect_trajectories(
        self,
        trajectories: Dict[str, Trajectory],
    ) -> Dict[str, Dict[str, np.ndarray]]:
        """Process trajectories and compute advantages."""
        processed = {}
        
        for agent_id, trajectory in trajectories.items():
            if agent_id not in self.agents:
                continue
            
            agent = self.agents[agent_id]
            
            states = np.array([e.state for e in trajectory.experiences])
            actions = np.array([e.action for e in trajectory.experiences])
            
            # Get value estimates
            values = np.array([agent.get_value(s) for s in states])
            
            # Compute GAE
            advantages = trajectory.compute_gae(
                values, self.config.gamma, self.config.gae_lambda
            )
            
            # Save old policy
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
                "returns": trajectory.returns,
                "advantages": advantages,
                "old_log_probs": old_log_probs,
            }
        
        return processed
    
    def update(
        self,
        processed_data: Dict[str, Dict[str, np.ndarray]],
    ) -> Dict[str, Any]:
        """Update all agents independently."""
        self._update_count += 1
        
        results = {
            "update_count": self._update_count,
            "agent_losses": {},
        }
        
        for agent_id, data in processed_data.items():
            if agent_id not in self.agents:
                continue
            
            agent = self.agents[agent_id]
            
            for epoch in range(self.config.n_epochs):
                n_samples = len(data["states"])
                indices = np.random.permutation(n_samples)
                
                for start in range(0, n_samples, self.config.batch_size):
                    end = min(start + self.config.batch_size, n_samples)
                    batch_indices = indices[start:end]
                    
                    loss_info = agent.update(
                        data["states"][batch_indices],
                        data["actions"][batch_indices],
                        data["returns"][batch_indices],
                        data["advantages"][batch_indices],
                        data["old_log_probs"][batch_indices],
                    )
            
            results["agent_losses"][agent_id] = loss_info
        
        return results
    
    def get_stats(self) -> Dict[str, Any]:
        """Get training statistics."""
        return {
            "n_agents": self.n_agents,
            "update_count": self._update_count,
            "agent_stats": {
                agent_id: agent.get_stats()
                for agent_id, agent in self.agents.items()
            },
        }
