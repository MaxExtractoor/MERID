"""
MERID MARL - Counterfactual Multi-Agent Policy Gradients (COMA)

COMA uses a centralized critic to compute counterfactual baselines:
- Critic estimates Q(s, a) for all joint actions
- Counterfactual baseline: what if this agent took a different action?
- Advantage = Q(s, a) - Σ π(a'|s) Q(s, (a', a_{-i}))

Reference: Foerster et al., "Counterfactual Multi-Agent Policy Gradients"
"""

from __future__ import annotations

import time
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
    NeuralNetwork,
    AgentRole,
)
from utils.logger import get_logger

logger = get_logger("learning.marl.coma")


@dataclass
class COMAConfig:
    """Configuration for COMA algorithm."""
    # Learning rates
    policy_lr: float = 5e-4
    critic_lr: float = 1e-3
    
    # Discount
    gamma: float = 0.99
    
    # Training
    n_epochs: int = 5
    batch_size: int = 32
    td_lambda: float = 0.8
    
    # Architecture
    hidden_dims: List[int] = field(default_factory=lambda: [128, 128])
    
    # Entropy regularization
    entropy_coef: float = 0.01
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "policy_lr": self.policy_lr,
            "critic_lr": self.critic_lr,
            "gamma": self.gamma,
            "td_lambda": self.td_lambda,
            "entropy_coef": self.entropy_coef,
        }


class COMACounterfactualCritic(MARLCritic):
    """
    Centralized critic for COMA that outputs Q-values for all actions
    of a specific agent, given the global state and other agents' actions.
    
    Input: [global_state, other_agents_actions, agent_id_onehot]
    Output: Q-values for all actions of the target agent
    """
    
    def __init__(
        self,
        global_state_dim: int,
        action_dim: int,
        n_agents: int,
        hidden_dims: List[int] = None,
    ):
        super().__init__(global_state_dim, action_dim, n_agents, hidden_dims)
        
        self.global_state_dim = global_state_dim
        
        # Input: global_state + (n_agents-1) * action_dim (other actions one-hot) + n_agents (agent id)
        input_dim = global_state_dim + (n_agents - 1) * action_dim + n_agents
        
        self.network = NeuralNetwork(
            input_dim, action_dim, hidden_dims, activation="relu"
        )
    
    def _build_input(
        self,
        global_state: np.ndarray,
        other_actions: np.ndarray,
        agent_idx: int,
    ) -> np.ndarray:
        """Build input vector for critic."""
        # One-hot encode other actions
        other_actions_onehot = []
        for i, action in enumerate(other_actions):
            if i != agent_idx:
                onehot = np.zeros(self.action_dim)
                onehot[int(action)] = 1.0
                other_actions_onehot.append(onehot)
        
        other_actions_flat = np.concatenate(other_actions_onehot) if other_actions_onehot else np.array([])
        
        # Agent ID one-hot
        agent_onehot = np.zeros(self.n_agents)
        agent_onehot[agent_idx] = 1.0
        
        # Concatenate
        return np.concatenate([global_state, other_actions_flat, agent_onehot])
    
    def forward(
        self,
        global_state: np.ndarray,
        other_actions: np.ndarray,
        agent_idx: int,
    ) -> np.ndarray:
        """Get Q-values for all actions of target agent."""
        input_vec = self._build_input(global_state, other_actions, agent_idx)
        return self.network.forward(input_vec)
    
    def get_value(
        self,
        state: np.ndarray,
        actions: Optional[np.ndarray] = None,
    ) -> float:
        """Get value (not used directly in COMA)."""
        return 0.0
    
    def get_q_values(
        self,
        global_state: np.ndarray,
        other_actions: np.ndarray,
        agent_idx: int,
    ) -> np.ndarray:
        """Get Q-values for all actions."""
        return self.forward(global_state, other_actions, agent_idx)
    
    def get_parameters(self) -> Dict[str, np.ndarray]:
        return self.network.get_parameters()
    
    def set_parameters(self, parameters: Dict[str, np.ndarray]) -> None:
        self.network.set_parameters(parameters)


class COMAAgent(MARLAgent):
    """COMA agent with policy network."""
    
    def __init__(
        self,
        agent_id: str,
        agent_idx: int,
        state_dim: int,
        action_dim: int,
        config: COMAConfig,
    ):
        super().__init__(agent_id, state_dim, action_dim, AgentRole.ACTOR)
        
        self.agent_idx = agent_idx
        self.config = config
        
        # Initialize policy
        self.policy = CategoricalPolicy(
            state_dim, action_dim, config.hidden_dims
        )
        
        # Training statistics
        self._policy_losses: List[float] = []
    
    def compute_counterfactual_advantage(
        self,
        q_values: np.ndarray,
        action: int,
        state: np.ndarray,
    ) -> float:
        """
        Compute counterfactual advantage.
        
        A(s, a) = Q(s, a) - Σ π(a'|s) Q(s, a')
        """
        # Get action probabilities
        logits = self.policy.forward(state)
        exp_logits = np.exp(logits - np.max(logits))
        probs = exp_logits / exp_logits.sum()
        
        # Baseline: expected Q-value under current policy
        baseline = np.sum(probs * q_values)
        
        # Advantage
        advantage = q_values[action] - baseline
        
        return advantage
    
    def update_policy(
        self,
        states: np.ndarray,
        actions: np.ndarray,
        advantages: np.ndarray,
    ) -> Dict[str, float]:
        """Update policy using policy gradient with counterfactual advantages."""
        policy_loss = 0.0
        entropy_loss = 0.0
        
        for i in range(len(states)):
            state = states[i]
            action = int(actions[i])
            advantage = advantages[i]
            
            # Log probability
            log_prob = self.policy.get_log_prob(state, action)
            
            # Policy gradient loss
            policy_loss -= log_prob * advantage
            
            # Entropy
            entropy = self.policy.get_entropy(state)
            entropy_loss -= entropy
        
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
                loss_plus = self._compute_loss(states, actions, advantages)
                
                params[key][flat_idx] -= 2 * epsilon
                self.policy.set_parameters(params)
                loss_minus = self._compute_loss(states, actions, advantages)
                
                params[key][flat_idx] += epsilon
                grad[flat_idx] = (loss_plus - loss_minus) / (2 * epsilon)
            
            params[key] -= self.config.policy_lr * grad
        
        self.policy.set_parameters(params)
        self._policy_losses.append(policy_loss)
        
        return {
            "policy_loss": policy_loss,
            "entropy_loss": entropy_loss,
            "total_loss": total_loss,
        }
    
    def _compute_loss(
        self,
        states: np.ndarray,
        actions: np.ndarray,
        advantages: np.ndarray,
    ) -> float:
        """Compute policy loss."""
        loss = 0.0
        for i in range(len(states)):
            log_prob = self.policy.get_log_prob(states[i], int(actions[i]))
            loss -= log_prob * advantages[i]
        return loss / len(states)


class COMA:
    """
    Counterfactual Multi-Agent Policy Gradients.
    
    Key features:
    - Centralized critic with counterfactual baselines
    - Decentralized actors
    - Credit assignment through counterfactual reasoning
    """
    
    def __init__(
        self,
        n_agents: int,
        state_dim: int,
        action_dim: int,
        global_state_dim: int,
        config: Optional[COMAConfig] = None,
    ):
        self.n_agents = n_agents
        self.state_dim = state_dim
        self.action_dim = action_dim
        self.global_state_dim = global_state_dim
        self.config = config or COMAConfig()
        
        # Initialize agents
        self.agents: Dict[str, COMAAgent] = {}
        for i in range(n_agents):
            agent_id = f"coma_agent_{i}"
            self.agents[agent_id] = COMAAgent(
                agent_id, i, state_dim, action_dim, self.config
            )
        
        # Centralized counterfactual critic
        self.critic = COMACounterfactualCritic(
            global_state_dim, action_dim, n_agents, self.config.hidden_dims
        )
        
        # Training statistics
        self._update_count = 0
        self._critic_losses: List[float] = []
        
        logger.info(
            "COMA initialized: %d agents, state_dim=%d, action_dim=%d",
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
    
    def compute_counterfactual_advantages(
        self,
        trajectories: Dict[str, Trajectory],
        global_states: List[np.ndarray],
        joint_actions: List[Dict[str, int]],
    ) -> Dict[str, np.ndarray]:
        """Compute counterfactual advantages for all agents."""
        advantages = {}
        
        for agent_id, trajectory in trajectories.items():
            if agent_id not in self.agents:
                continue
            
            agent = self.agents[agent_id]
            agent_advantages = []
            
            for t, exp in enumerate(trajectory.experiences):
                if t >= len(global_states) or t >= len(joint_actions):
                    break
                
                global_state = global_states[t]
                joint_action = joint_actions[t]
                
                # Get all actions as array
                all_actions = np.array([
                    joint_action.get(f"coma_agent_{i}", 0)
                    for i in range(self.n_agents)
                ])
                
                # Get Q-values for this agent
                q_values = self.critic.get_q_values(
                    global_state, all_actions, agent.agent_idx
                )
                
                # Compute counterfactual advantage
                advantage = agent.compute_counterfactual_advantage(
                    q_values, int(exp.action), exp.state
                )
                
                agent_advantages.append(advantage)
            
            advantages[agent_id] = np.array(agent_advantages)
        
        return advantages
    
    def update(
        self,
        trajectories: Dict[str, Trajectory],
        global_states: List[np.ndarray],
        joint_actions: List[Dict[str, int]],
    ) -> Dict[str, Any]:
        """Update all agents and critic."""
        self._update_count += 1
        
        results = {
            "update_count": self._update_count,
            "agent_losses": {},
            "critic_loss": 0.0,
        }
        
        # Update critic first
        critic_loss = self._update_critic(trajectories, global_states, joint_actions)
        results["critic_loss"] = critic_loss
        self._critic_losses.append(critic_loss)
        
        # Compute counterfactual advantages
        advantages = self.compute_counterfactual_advantages(
            trajectories, global_states, joint_actions
        )
        
        # Update each agent's policy
        for agent_id, trajectory in trajectories.items():
            if agent_id not in self.agents or agent_id not in advantages:
                continue
            
            agent = self.agents[agent_id]
            
            states = np.array([e.state for e in trajectory.experiences])
            actions = np.array([e.action for e in trajectory.experiences])
            agent_advantages = advantages[agent_id]
            
            # Normalize advantages
            if len(agent_advantages) > 1:
                agent_advantages = (agent_advantages - agent_advantages.mean()) / (agent_advantages.std() + 1e-8)
            
            loss_info = agent.update_policy(states, actions, agent_advantages)
            results["agent_losses"][agent_id] = loss_info
        
        return results
    
    def _update_critic(
        self,
        trajectories: Dict[str, Trajectory],
        global_states: List[np.ndarray],
        joint_actions: List[Dict[str, int]],
    ) -> float:
        """Update centralized critic using TD learning."""
        total_loss = 0.0
        n_samples = 0
        
        for agent_id, trajectory in trajectories.items():
            if agent_id not in self.agents:
                continue
            
            agent = self.agents[agent_id]
            
            for t, exp in enumerate(trajectory.experiences):
                if t >= len(global_states) - 1 or t >= len(joint_actions):
                    break
                
                global_state = global_states[t]
                next_global_state = global_states[t + 1]
                joint_action = joint_actions[t]
                
                all_actions = np.array([
                    joint_action.get(f"coma_agent_{i}", 0)
                    for i in range(self.n_agents)
                ])
                
                # Current Q-value
                q_values = self.critic.get_q_values(global_state, all_actions, agent.agent_idx)
                current_q = q_values[int(exp.action)]
                
                # Target Q-value (TD target)
                if exp.done:
                    target_q = exp.reward
                else:
                    next_q_values = self.critic.get_q_values(
                        next_global_state, all_actions, agent.agent_idx
                    )
                    target_q = exp.reward + self.config.gamma * np.max(next_q_values)
                
                # TD error
                td_error = target_q - current_q
                total_loss += td_error ** 2
                n_samples += 1
        
        if n_samples == 0:
            return 0.0
        
        loss = total_loss / n_samples
        
        # Update critic parameters
        params = self.critic.get_parameters()
        epsilon = 1e-4
        
        for key in params:
            grad = np.zeros_like(params[key])
            n_grad_samples = min(5, params[key].size)
            indices = np.random.choice(params[key].size, n_grad_samples, replace=False)
            
            for idx in indices:
                flat_idx = np.unravel_index(idx, params[key].shape)
                
                params[key][flat_idx] += epsilon
                self.critic.set_parameters(params)
                loss_plus = self._compute_critic_loss(trajectories, global_states, joint_actions)
                
                params[key][flat_idx] -= 2 * epsilon
                self.critic.set_parameters(params)
                loss_minus = self._compute_critic_loss(trajectories, global_states, joint_actions)
                
                params[key][flat_idx] += epsilon
                grad[flat_idx] = (loss_plus - loss_minus) / (2 * epsilon)
            
            params[key] -= self.config.critic_lr * grad
        
        self.critic.set_parameters(params)
        
        return loss
    
    def _compute_critic_loss(
        self,
        trajectories: Dict[str, Trajectory],
        global_states: List[np.ndarray],
        joint_actions: List[Dict[str, int]],
    ) -> float:
        """Compute critic TD loss."""
        total_loss = 0.0
        n_samples = 0
        
        for agent_id, trajectory in trajectories.items():
            if agent_id not in self.agents:
                continue
            
            agent = self.agents[agent_id]
            
            for t, exp in enumerate(trajectory.experiences):
                if t >= len(global_states) - 1:
                    break
                
                global_state = global_states[t]
                joint_action = joint_actions[t]
                
                all_actions = np.array([
                    joint_action.get(f"coma_agent_{i}", 0)
                    for i in range(self.n_agents)
                ])
                
                q_values = self.critic.get_q_values(global_state, all_actions, agent.agent_idx)
                current_q = q_values[int(exp.action)]
                
                if exp.done:
                    target_q = exp.reward
                else:
                    next_global_state = global_states[t + 1]
                    next_q_values = self.critic.get_q_values(
                        next_global_state, all_actions, agent.agent_idx
                    )
                    target_q = exp.reward + self.config.gamma * np.max(next_q_values)
                
                total_loss += (target_q - current_q) ** 2
                n_samples += 1
        
        return total_loss / max(1, n_samples)
    
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
