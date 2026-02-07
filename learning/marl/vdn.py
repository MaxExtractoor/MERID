"""
MERID MARL - Value Decomposition Networks (VDN)

VDN decomposes the joint action-value function as a simple sum:
Q_tot = Σ Q_i(s_i, a_i)

This is a special case of QMIX with identity mixing.
Simpler but less expressive than QMIX.

Reference: Sunehag et al., "Value-Decomposition Networks For Cooperative Multi-Agent Learning"
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
    ReplayBuffer,
    QCritic,
    AgentRole,
)
from utils.logger import get_logger

logger = get_logger("learning.marl.vdn")


@dataclass
class VDNConfig:
    """Configuration for VDN algorithm."""
    # Learning rate
    lr: float = 5e-4
    
    # Discount
    gamma: float = 0.99
    
    # Target network
    target_update_interval: int = 100
    tau: float = 0.01
    
    # Exploration
    epsilon_start: float = 1.0
    epsilon_end: float = 0.05
    epsilon_decay_steps: int = 50000
    
    # Training
    batch_size: int = 32
    buffer_size: int = 50000
    
    # Architecture
    hidden_dims: List[int] = field(default_factory=lambda: [64, 64])
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "lr": self.lr,
            "gamma": self.gamma,
            "target_update_interval": self.target_update_interval,
            "epsilon_start": self.epsilon_start,
            "epsilon_end": self.epsilon_end,
            "batch_size": self.batch_size,
        }


class VDNAgent(MARLAgent):
    """VDN agent with individual Q-network."""
    
    def __init__(
        self,
        agent_id: str,
        agent_idx: int,
        state_dim: int,
        action_dim: int,
        config: VDNConfig,
    ):
        super().__init__(agent_id, state_dim, action_dim, AgentRole.ACTOR)
        
        self.agent_idx = agent_idx
        self.config = config
        
        # Q-network
        self.q_network = QCritic(state_dim, action_dim, config.hidden_dims)
        
        # Target Q-network
        self.target_q_network = QCritic(state_dim, action_dim, config.hidden_dims)
        self._sync_target()
        
        # Exploration
        self._epsilon = config.epsilon_start
        self._step_count = 0
    
    def _sync_target(self) -> None:
        """Sync target network with main network."""
        self.target_q_network.set_parameters(self.q_network.get_parameters())
    
    def soft_update_target(self) -> None:
        """Soft update target network."""
        main_params = self.q_network.get_parameters()
        target_params = self.target_q_network.get_parameters()
        
        for key in main_params:
            target_params[key] = (
                self.config.tau * main_params[key] +
                (1 - self.config.tau) * target_params[key]
            )
        
        self.target_q_network.set_parameters(target_params)
    
    def get_action(self, state: np.ndarray, deterministic: bool = False) -> Tuple[int, float]:
        """Get action using epsilon-greedy."""
        self._step_count += 1
        
        # Decay epsilon
        decay_progress = min(1.0, self._step_count / self.config.epsilon_decay_steps)
        self._epsilon = (
            self.config.epsilon_start +
            (self.config.epsilon_end - self.config.epsilon_start) * decay_progress
        )
        
        if not deterministic and np.random.random() < self._epsilon:
            action = np.random.randint(0, self.action_dim)
            return action, 0.0
        
        q_values = self.q_network.forward(state)
        action = int(np.argmax(q_values))
        
        return action, float(q_values[action])
    
    def get_q_values(self, state: np.ndarray) -> np.ndarray:
        """Get Q-values for all actions."""
        return self.q_network.forward(state)
    
    def get_target_q_values(self, state: np.ndarray) -> np.ndarray:
        """Get target Q-values for all actions."""
        return self.target_q_network.forward(state)


class VDN:
    """
    Value Decomposition Networks.
    
    Key features:
    - Simple additive decomposition: Q_tot = Σ Q_i
    - Per-agent Q-networks
    - Shared reward signal
    - Decentralized execution with centralized training
    """
    
    def __init__(
        self,
        n_agents: int,
        state_dim: int,
        action_dim: int,
        config: Optional[VDNConfig] = None,
    ):
        self.n_agents = n_agents
        self.state_dim = state_dim
        self.action_dim = action_dim
        self.config = config or VDNConfig()
        
        # Initialize agents
        self.agents: Dict[str, VDNAgent] = {}
        for i in range(n_agents):
            agent_id = f"vdn_agent_{i}"
            self.agents[agent_id] = VDNAgent(
                agent_id, i, state_dim, action_dim, self.config
            )
        
        # Replay buffer
        self.buffer = ReplayBuffer(self.config.buffer_size)
        
        # Training statistics
        self._update_count = 0
        self._losses: List[float] = []
        
        logger.info(
            "VDN initialized: %d agents, state_dim=%d, action_dim=%d",
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
    
    def get_q_tot(
        self,
        observations: Dict[str, np.ndarray],
        actions: Dict[str, int],
    ) -> float:
        """Get total Q-value (sum of individual Q-values)."""
        q_tot = 0.0
        for agent_id, agent in self.agents.items():
            if agent_id in observations and agent_id in actions:
                q_values = agent.get_q_values(observations[agent_id])
                q_tot += q_values[actions[agent_id]]
        return q_tot
    
    def store_transition(
        self,
        observations: Dict[str, np.ndarray],
        actions: Dict[str, int],
        rewards: Dict[str, float],
        next_observations: Dict[str, np.ndarray],
        dones: Dict[str, bool],
    ) -> None:
        """Store transition in replay buffer."""
        # Shared reward (sum or average)
        shared_reward = sum(rewards.values()) / len(rewards) if rewards else 0.0
        
        for agent_id in self.agents:
            if agent_id in observations:
                exp = Experience(
                    state=observations[agent_id],
                    action=actions.get(agent_id, 0),
                    reward=shared_reward,
                    next_state=next_observations.get(agent_id, observations[agent_id]),
                    done=any(dones.values()),
                    agent_id=agent_id,
                    info={
                        "all_observations": observations,
                        "all_actions": actions,
                        "all_next_observations": next_observations,
                    },
                )
                self.buffer.add(exp)
    
    def update(self) -> Dict[str, Any]:
        """Update all Q-networks."""
        if len(self.buffer) < self.config.batch_size:
            return {"update_count": self._update_count, "loss": 0.0}
        
        self._update_count += 1
        
        # Sample batch
        batch = self.buffer.sample(self.config.batch_size)
        
        # Compute loss and update
        loss = self._compute_and_update(batch)
        self._losses.append(loss)
        
        # Update target networks
        if self._update_count % self.config.target_update_interval == 0:
            for agent in self.agents.values():
                agent._sync_target()
        else:
            for agent in self.agents.values():
                agent.soft_update_target()
        
        return {
            "update_count": self._update_count,
            "loss": loss,
            "epsilon": list(self.agents.values())[0]._epsilon if self.agents else 0,
        }
    
    def _compute_and_update(self, batch: List[Experience]) -> float:
        """Compute VDN loss and update networks."""
        total_loss = 0.0
        
        for exp in batch:
            all_obs = exp.info.get("all_observations", {})
            all_actions = exp.info.get("all_actions", {})
            all_next_obs = exp.info.get("all_next_observations", {})
            
            # Current Q_tot
            q_tot = 0.0
            for agent_id, agent in self.agents.items():
                if agent_id in all_obs:
                    q_values = agent.get_q_values(all_obs[agent_id])
                    action = all_actions.get(agent_id, 0)
                    q_tot += q_values[action]
            
            # Target Q_tot (max over actions for each agent)
            target_q_tot = 0.0
            for agent_id, agent in self.agents.items():
                if agent_id in all_next_obs:
                    target_q_values = agent.get_target_q_values(all_next_obs[agent_id])
                    target_q_tot += np.max(target_q_values)
            
            # TD target
            if exp.done:
                td_target = exp.reward
            else:
                td_target = exp.reward + self.config.gamma * target_q_tot
            
            # TD error
            td_error = td_target - q_tot
            total_loss += td_error ** 2
        
        loss = total_loss / len(batch)
        
        # Update each agent's Q-network
        for agent in self.agents.values():
            self._update_agent(agent, batch)
        
        return loss
    
    def _update_agent(self, agent: VDNAgent, batch: List[Experience]) -> None:
        """Update agent's Q-network using gradient descent."""
        params = agent.q_network.get_parameters()
        epsilon = 1e-4
        
        for key in params:
            grad = np.zeros_like(params[key])
            n_samples = min(5, params[key].size)
            indices = np.random.choice(params[key].size, n_samples, replace=False)
            
            for idx in indices:
                flat_idx = np.unravel_index(idx, params[key].shape)
                
                params[key][flat_idx] += epsilon
                agent.q_network.set_parameters(params)
                loss_plus = self._compute_batch_loss(batch)
                
                params[key][flat_idx] -= 2 * epsilon
                agent.q_network.set_parameters(params)
                loss_minus = self._compute_batch_loss(batch)
                
                params[key][flat_idx] += epsilon
                grad[flat_idx] = (loss_plus - loss_minus) / (2 * epsilon)
            
            params[key] -= self.config.lr * grad
        
        agent.q_network.set_parameters(params)
    
    def _compute_batch_loss(self, batch: List[Experience]) -> float:
        """Compute loss for a batch."""
        total_loss = 0.0
        
        for exp in batch:
            all_obs = exp.info.get("all_observations", {})
            all_actions = exp.info.get("all_actions", {})
            all_next_obs = exp.info.get("all_next_observations", {})
            
            q_tot = 0.0
            for agent_id, agent in self.agents.items():
                if agent_id in all_obs:
                    q_values = agent.get_q_values(all_obs[agent_id])
                    action = all_actions.get(agent_id, 0)
                    q_tot += q_values[action]
            
            target_q_tot = 0.0
            for agent_id, agent in self.agents.items():
                if agent_id in all_next_obs:
                    target_q_values = agent.get_target_q_values(all_next_obs[agent_id])
                    target_q_tot += np.max(target_q_values)
            
            if exp.done:
                td_target = exp.reward
            else:
                td_target = exp.reward + self.config.gamma * target_q_tot
            
            total_loss += (td_target - q_tot) ** 2
        
        return total_loss / len(batch)
    
    def get_stats(self) -> Dict[str, Any]:
        """Get training statistics."""
        return {
            "n_agents": self.n_agents,
            "update_count": self._update_count,
            "buffer_size": len(self.buffer),
            "avg_loss": np.mean(self._losses[-100:]) if self._losses else 0,
            "epsilon": list(self.agents.values())[0]._epsilon if self.agents else 0,
        }
