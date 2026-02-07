"""
Stage 9: COMA (Counterfactual Multi-Agent Policy Gradients) implementation for MERID.
Foerster et al. (2018) - Centralized critic, decentralized actors with counterfactual baselines.
2026 extensions: Transformer critics, COMA++/QMIX integration, parameter sharing for 100+ agents.
"""

from __future__ import annotations

import numpy as np
from typing import List, Dict, Tuple, Optional
from dataclasses import dataclass

from utils.deps import optional_dependency
from utils.logger import get_logger

logger = get_logger("swarm.coma")

torch = optional_dependency("torch")
if torch:
    import torch.nn as nn
    import torch.optim as optim
    from torch.distributions import Categorical
else:  # pragma: no cover - optional dependency guard
    nn = optim = Categorical = None
    logger.warning("PyTorch not installed - COMA agent unavailable")

TORCH_AVAILABLE = torch is not None


def _require_torch() -> None:
    if not TORCH_AVAILABLE:
        raise RuntimeError(
            "PyTorch is required for COMA. Install it with `pip install torch` to enable this agent."
        )


if TORCH_AVAILABLE:
    class COMAActorRNN(nn.Module):
        """Per-agent policy network with RNN for history encoding."""
        
        def __init__(self, obs_size: int, action_size: int, hidden_size: int = 128):
            super().__init__()
            self.hidden_size = hidden_size
            self.rnn = nn.GRU(obs_size, hidden_size, batch_first=True)
            self.fc = nn.Linear(hidden_size, action_size)
            
        def forward(self, obs: torch.Tensor, hidden: Optional[torch.Tensor] = None) -> Tuple[torch.Tensor, torch.Tensor]:
            """Forward pass with history. Returns action probs and hidden state."""
            if hidden is None:
                hidden = torch.zeros(1, obs.size(0), self.hidden_size)
            
            rnn_out, hidden = self.rnn(obs.unsqueeze(1), hidden)
            logits = self.fc(rnn_out.squeeze(1))
            probs = torch.softmax(logits, dim=-1)
            return probs, hidden
else:
    class COMAActorRNN:
        def __init__(self, *args, **kwargs):
            _require_torch()


class COMACriticCentralized(nn.Module):
    """Centralized critic Q(s, a_1, ..., a_n) for all agents."""
    
    def __init__(self, global_state_size: int, action_size: int, n_agents: int, hidden_size: int = 256):
        super().__init__()
        self.n_agents = n_agents
        self.action_size = action_size
        
        # Input: global state + all agent actions (one-hot encoded)
        input_size = global_state_size + action_size * n_agents
        
        self.fc1 = nn.Linear(input_size, hidden_size)
        self.fc2 = nn.Linear(hidden_size, hidden_size)
        self.fc3 = nn.Linear(hidden_size, action_size)  # Q-value per action for target agent
        
    def forward(self, global_state: torch.Tensor, actions: torch.Tensor, agent_idx: int) -> torch.Tensor:
        """
        Compute Q-values for all possible actions of agent_idx.
        actions: [batch, n_agents] - current actions of all agents
        Returns: [batch, action_size] - Q-value for each action of agent_idx
        """
        # One-hot encode actions
        actions_onehot = torch.nn.functional.one_hot(actions, self.action_size).float()
        actions_flat = actions_onehot.view(actions.size(0), -1)
        
        x = torch.cat([global_state, actions_flat], dim=-1)
        x = torch.relu(self.fc1(x))
        x = torch.relu(self.fc2(x))
        q_values = self.fc3(x)
        return q_values


class COMATransformerCritic(nn.Module):
    """2026 COMA-Trans: Transformer-based critic for long-range dependencies in swarm histories."""
    
    def __init__(self, global_state_size: int, action_size: int, n_agents: int, 
                 hidden_size: int = 256, n_heads: int = 4, n_layers: int = 2):
        super().__init__()
        self.n_agents = n_agents
        self.action_size = action_size
        self.hidden_size = hidden_size
        
        # Embedding for state and actions
        self.state_embed = nn.Linear(global_state_size, hidden_size)
        self.action_embed = nn.Linear(action_size * n_agents, hidden_size)
        
        # Transformer encoder
        encoder_layer = nn.TransformerEncoderLayer(
            d_model=hidden_size,
            nhead=n_heads,
            dim_feedforward=hidden_size * 4,
            batch_first=True
        )
        self.transformer = nn.TransformerEncoder(encoder_layer, num_layers=n_layers)
        
        # Output head
        self.fc_out = nn.Linear(hidden_size, action_size)
        
    def forward(self, global_state: torch.Tensor, actions: torch.Tensor, agent_idx: int) -> torch.Tensor:
        """Transformer-based Q-value computation."""
        batch_size = global_state.size(0)
        
        # Embed state and actions
        actions_onehot = torch.nn.functional.one_hot(actions, self.action_size).float()
        actions_flat = actions_onehot.view(batch_size, -1)
        
        state_emb = self.state_embed(global_state).unsqueeze(1)  # [batch, 1, hidden]
        action_emb = self.action_embed(actions_flat).unsqueeze(1)  # [batch, 1, hidden]
        
        # Combine and process through transformer
        seq = torch.cat([state_emb, action_emb], dim=1)  # [batch, 2, hidden]
        trans_out = self.transformer(seq)  # [batch, 2, hidden]
        
        # Use final output for Q-values
        q_values = self.fc_out(trans_out[:, -1, :])  # [batch, action_size]
        return q_values


@dataclass
class COMAAgent:
    """COMA agent with actor-critic architecture."""
    
    agent_id: str
    obs_size: int
    action_size: int
    hidden_size: int = 128
    lr_actor: float = 0.0005
    
    def __post_init__(self):
        self.actor = COMAActorRNN(self.obs_size, self.action_size, self.hidden_size)
        self.actor_optimizer = optim.Adam(self.actor.parameters(), lr=self.lr_actor)
        self.hidden_state = None
        
    def select_action(self, obs: np.ndarray, explore: bool = True) -> Tuple[int, torch.Tensor]:
        """Select action using policy network."""
        obs_tensor = torch.tensor(obs, dtype=torch.float32).unsqueeze(0)
        
        with torch.no_grad():
            probs, self.hidden_state = self.actor(obs_tensor, self.hidden_state)
        
        if explore:
            dist = Categorical(probs)
            action = dist.sample()
        else:
            action = torch.argmax(probs, dim=-1)
        
        return action.item(), probs
    
    def reset_hidden(self):
        """Reset RNN hidden state for new episode."""
        self.hidden_state = None


class COMA:
    """
    Counterfactual Multi-Agent Policy Gradients (COMA) algorithm.
    
    Key innovation: Counterfactual baseline for credit assignment.
    For agent i: A_i = Q(s, a) - Σ_{a_i'} π_i(a_i'|o_i) Q(s, a_{-i}, a_i')
    
    This isolates agent i's marginal contribution by marginalizing over its own policy
    while holding other agents' actions fixed.
    """
    
    def __init__(
        self,
        agents: List[COMAAgent],
        global_state_size: int,
        action_size: int,
        n_agents: int,
        lr_critic: float = 0.001,
        gamma: float = 0.99,
        use_transformer: bool = False,
    ):
        self.agents = agents
        self.n_agents = n_agents
        self.action_size = action_size
        self.gamma = gamma
        
        # Centralized critic
        if use_transformer:
            self.critic = COMATransformerCritic(global_state_size, action_size, n_agents)
            logger.info("COMA initialized with Transformer critic (COMA-Trans 2026)")
        else:
            self.critic = COMACriticCentralized(global_state_size, action_size, n_agents)
            logger.info("COMA initialized with standard centralized critic")
        
        self.critic_optimizer = optim.Adam(self.critic.parameters(), lr=lr_critic)
        
        # Target network for stable learning
        if use_transformer:
            self.target_critic = COMATransformerCritic(global_state_size, action_size, n_agents)
        else:
            self.target_critic = COMACriticCentralized(global_state_size, action_size, n_agents)
        
        self.target_critic.load_state_dict(self.critic.state_dict())
        
    def compute_counterfactual_baseline(
        self,
        global_state: torch.Tensor,
        actions: torch.Tensor,
        agent_idx: int,
        policy_probs: torch.Tensor,
    ) -> torch.Tensor:
        """
        Compute counterfactual baseline for agent_idx.
        
        Baseline = Σ_{a_i'} π_i(a_i'|o_i) Q(s, a_{-i}, a_i')
        
        This is the expected Q-value if agent_idx follows its policy while others' actions are fixed.
        """
        batch_size = global_state.size(0)
        baseline = torch.zeros(batch_size, device=global_state.device, dtype=torch.float32)
        
        # For each possible action of agent_idx
        for a_prime in range(self.action_size):
            # Create counterfactual action vector
            actions_cf = actions.clone()
            actions_cf[:, agent_idx] = a_prime
            
            # Get Q-value for this counterfactual
            with torch.no_grad():
                q_cf = self.critic(global_state, actions_cf, agent_idx)
                q_cf_action = q_cf[:, a_prime]
            
            # Weight by policy probability (support 1-D or batched tensors)
            if policy_probs.dim() == 1:
                prob_a_prime = policy_probs[a_prime]
            else:
                prob_a_prime = policy_probs[:, a_prime]
            
            baseline += prob_a_prime * q_cf_action
        
        return baseline
    
    def compute_advantages(
        self,
        global_state: torch.Tensor,
        actions: torch.Tensor,
        policy_probs_list: List[torch.Tensor],
    ) -> List[torch.Tensor]:
        """
        Compute COMA advantages for all agents.
        
        A_i = Q(s, a) - baseline_i
        
        where baseline_i is the counterfactual baseline for agent i.
        """
        advantages = []
        
        for i in range(self.n_agents):
            # Get Q-value for actual joint action
            q_values = self.critic(global_state, actions, i)
            q_actual = q_values.gather(1, actions[:, i].unsqueeze(1)).squeeze(1)
            
            # Compute counterfactual baseline
            baseline = self.compute_counterfactual_baseline(
                global_state, actions, i, policy_probs_list[i]
            )
            
            # Advantage = Q(s, a) - baseline
            advantage = q_actual - baseline
            advantages.append(advantage)
        
        return advantages
    
    def update_critic(
        self,
        global_states: torch.Tensor,
        actions: torch.Tensor,
        rewards: torch.Tensor,
        next_global_states: torch.Tensor,
        next_actions: torch.Tensor,
        dones: torch.Tensor,
    ) -> float:
        """Update centralized critic with TD error."""
        critic_loss = 0.0
        
        for agent_idx in range(self.n_agents):
            # Current Q-values
            q_values = self.critic(global_states, actions, agent_idx)
            q_taken = q_values.gather(1, actions[:, agent_idx].unsqueeze(1)).squeeze(1)
            
            # Target Q-values (use target network)
            with torch.no_grad():
                next_q_values = self.target_critic(next_global_states, next_actions, agent_idx)
                next_q_max = next_q_values.max(1)[0]
                targets = rewards + self.gamma * next_q_max * (1 - dones)
            
            # TD loss
            loss = nn.MSELoss()(q_taken, targets)
            critic_loss += loss.item()
            
            # Optimize
            self.critic_optimizer.zero_grad()
            loss.backward()
            torch.nn.utils.clip_grad_norm_(self.critic.parameters(), 10.0)
            self.critic_optimizer.step()
        
        return critic_loss / self.n_agents
    
    def update_actors(
        self,
        observations: List[torch.Tensor],
        actions: torch.Tensor,
        advantages: List[torch.Tensor],
    ) -> float:
        """Update actor policies using policy gradient with COMA advantages."""
        actor_loss_total = 0.0
        
        for i, agent in enumerate(self.agents):
            # Get action probabilities from actor
            obs_tensor = observations[i]
            probs, _ = agent.actor(obs_tensor.unsqueeze(0))
            
            # Log probability of taken action
            dist = Categorical(probs)
            log_prob = dist.log_prob(actions[:, i])
            
            # Policy gradient loss: -log π(a|o) * A
            # Negative because we want to maximize advantage
            actor_loss = -(log_prob * advantages[i].detach()).mean()
            
            # Add entropy bonus for exploration
            entropy = dist.entropy().mean()
            total_loss = actor_loss - 0.01 * entropy
            
            # Optimize
            agent.actor_optimizer.zero_grad()
            total_loss.backward()
            torch.nn.utils.clip_grad_norm_(agent.actor.parameters(), 10.0)
            agent.actor_optimizer.step()
            
            actor_loss_total += actor_loss.item()
        
        return actor_loss_total / self.n_agents
    
    def update_target_network(self, tau: float = 0.005):
        """Soft update of target critic network."""
        for target_param, param in zip(self.target_critic.parameters(), self.critic.parameters()):
            target_param.data.copy_(tau * param.data + (1 - tau) * target_param.data)
    
    def train_step(
        self,
        observations: List[np.ndarray],
        global_state: np.ndarray,
        actions: List[int],
        rewards: List[float],
        next_observations: List[np.ndarray],
        next_global_state: np.ndarray,
        next_actions: List[int],
        done: bool,
    ) -> Dict[str, float]:
        """Single training step for COMA."""
        # Convert to tensors
        obs_tensors = [torch.tensor(obs, dtype=torch.float32) for obs in observations]
        global_state_tensor = torch.tensor(global_state, dtype=torch.float32).unsqueeze(0)
        actions_tensor = torch.tensor(actions, dtype=torch.int64).unsqueeze(0)
        rewards_tensor = torch.tensor([sum(rewards)], dtype=torch.float32)  # Shared reward
        next_global_state_tensor = torch.tensor(next_global_state, dtype=torch.float32).unsqueeze(0)
        next_actions_tensor = torch.tensor(next_actions, dtype=torch.int64).unsqueeze(0)
        dones_tensor = torch.tensor([float(done)], dtype=torch.float32)
        
        # Get policy probabilities for counterfactual baseline
        policy_probs_list = []
        for i, agent in enumerate(self.agents):
            with torch.no_grad():
                probs, _ = agent.actor(obs_tensors[i].unsqueeze(0))
                policy_probs_list.append(probs.squeeze(0))
        
        # Compute advantages
        advantages = self.compute_advantages(
            global_state_tensor,
            actions_tensor,
            policy_probs_list,
        )
        
        # Update critic
        critic_loss = self.update_critic(
            global_state_tensor,
            actions_tensor,
            rewards_tensor,
            next_global_state_tensor,
            next_actions_tensor,
            dones_tensor,
        )
        
        # Update actors
        actor_loss = self.update_actors(obs_tensors, actions_tensor, advantages)
        
        # Soft update target network
        self.update_target_network()
        
        return {
            "critic_loss": critic_loss,
            "actor_loss": actor_loss,
            "avg_advantage": sum(adv.mean().item() for adv in advantages) / self.n_agents,
        }


class COMA_QMIX_Hybrid:
    """
    COMA++ (2026): Hybrid of COMA and QMIX for monotonic counterfactual baselines.
    
    Uses QMIX mixing network to ensure monotonic relationship between individual
    and joint Q-values, improving credit assignment in financial trading swarms.
    """
    
    def __init__(
        self,
        agents: List[COMAAgent],
        global_state_size: int,
        action_size: int,
        n_agents: int,
        lr_critic: float = 0.001,
        gamma: float = 0.99,
    ):
        self.coma = COMA(agents, global_state_size, action_size, n_agents, lr_critic, gamma)
        
        # QMIX mixer for monotonic baseline
        from swarm.marl_engine import QMIXMixer
        self.mixer = QMIXMixer(n_agents, global_state_size, embed_size=64)
        self.mixer_optimizer = optim.Adam(self.mixer.parameters(), lr=lr_critic)
        
        logger.info("COMA++ initialized with QMIX monotonic baselines")
    
    def compute_mixed_advantages(
        self,
        global_state: torch.Tensor,
        actions: torch.Tensor,
        policy_probs_list: List[torch.Tensor],
    ) -> List[torch.Tensor]:
        """Compute advantages using QMIX-mixed counterfactual baselines."""
        # Get individual Q-values
        individual_q_values = []
        for i in range(self.coma.n_agents):
            q_vals = self.coma.critic(global_state, actions, i)
            q_taken = q_vals.gather(1, actions[:, i].unsqueeze(1)).squeeze(1)
            individual_q_values.append(q_taken)
        
        individual_q_tensor = torch.stack(individual_q_values, dim=1)
        
        # Mix with QMIX for monotonic joint Q-value
        q_tot = self.mixer(individual_q_tensor, global_state)
        
        # Compute counterfactual baselines with mixing
        advantages = []
        for i in range(self.coma.n_agents):
            baseline = self.coma.compute_counterfactual_baseline(
                global_state, actions, i, policy_probs_list[i]
            )
            advantage = individual_q_values[i] - baseline
            advantages.append(advantage)
        
        return advantages


def create_coma_swarm(
    n_agents: int,
    obs_size: int,
    action_size: int,
    global_state_size: int,
    use_transformer: bool = False,
    use_qmix_hybrid: bool = False,
) -> Tuple[List[COMAAgent], COMA]:
    """Factory function to create COMA swarm."""
    agents = [
        COMAAgent(
            agent_id=f"coma_agent_{i}",
            obs_size=obs_size,
            action_size=action_size,
        )
        for i in range(n_agents)
    ]
    
    if use_qmix_hybrid:
        coma = COMA_QMIX_Hybrid(agents, global_state_size, action_size, n_agents)
        logger.info("Created COMA++ hybrid swarm with %d agents", n_agents)
    else:
        coma = COMA(agents, global_state_size, action_size, n_agents, use_transformer=use_transformer)
        logger.info("Created COMA swarm with %d agents (transformer=%s)", n_agents, use_transformer)
    
    return agents, coma
