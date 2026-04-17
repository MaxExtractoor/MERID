"""Stage 9: Multi-Agent Reinforcement Learning (MARL) engine for MERID swarm."""

from __future__ import annotations

import random
from collections import deque
from dataclasses import dataclass, field
from typing import Deque, Dict, List, Optional, Tuple

import numpy as np

from utils.deps import optional_dependency
from utils.logger import get_logger

logger = get_logger("swarm.marl")

torch = optional_dependency("torch")
if torch:
    import torch.nn as nn
    import torch.optim as optim
    from torch.distributions import Categorical
else:  # pragma: no cover - optional dependency guard
    nn = optim = Categorical = None
    logger.warning("PyTorch not installed - MARL engine unavailable")

TORCH_AVAILABLE = torch is not None


def _require_torch() -> None:
    if not TORCH_AVAILABLE:
        raise RuntimeError(
            "PyTorch is required for the MARL engine. Install it with `pip install torch`."
        )


# ---------------------------------------------------------------------------
# Q-Network and DQN Agent
# ---------------------------------------------------------------------------


if TORCH_AVAILABLE:
    class QNetwork(nn.Module):
        """Deep Q-Network for value function approximation."""

        def __init__(self, state_size: int, action_size: int, hidden_size: int = 128):
            super().__init__()
            self.fc1 = nn.Linear(state_size, hidden_size)
            self.fc2 = nn.Linear(hidden_size, hidden_size)
            self.fc3 = nn.Linear(hidden_size, action_size)

        def forward(self, state: torch.Tensor) -> torch.Tensor:
            x = torch.relu(self.fc1(state))
            x = torch.relu(self.fc2(x))
            return self.fc3(x)


    class DuelingQNetwork(nn.Module):
        """Dueling DQN architecture for better action-value decomposition."""

        def __init__(self, state_size: int, action_size: int, hidden_size: int = 128):
            super().__init__()
            self.feature = nn.Sequential(
                nn.Linear(state_size, hidden_size),
                nn.ReLU(),
            )
            self.value_stream = nn.Sequential(
                nn.Linear(hidden_size, hidden_size),
                nn.ReLU(),
                nn.Linear(hidden_size, 1),
            )
            self.advantage_stream = nn.Sequential(
                nn.Linear(hidden_size, hidden_size),
                nn.ReLU(),
                nn.Linear(hidden_size, action_size),
            )

        def forward(self, state: torch.Tensor) -> torch.Tensor:
            features = self.feature(state)
            value = self.value_stream(features)
            advantage = self.advantage_stream(features)
            # Q(s,a) = V(s) + (A(s,a) - mean(A(s,a)))
            q_values = value + (advantage - advantage.mean(dim=1, keepdim=True))
            return q_values
else:
    class QNetwork:
        def __init__(self, *args, **kwargs):
            _require_torch()

    class DuelingQNetwork:
        def __init__(self, *args, **kwargs):
            _require_torch()


@dataclass
class MARLAgent:
    """Multi-agent reinforcement learning agent with experience replay."""

    agent_id: str
    state_size: int
    action_size: int
    gamma: float = 0.99
    epsilon: float = 1.0
    epsilon_min: float = 0.01
    epsilon_decay: float = 0.995
    buffer_size: int = 10000
    batch_size: int = 64
    lr: float = 0.001
    use_dueling: bool = True

    def __post_init__(self):
        if self.use_dueling:
            self.q_network = DuelingQNetwork(self.state_size, self.action_size)
            self.target_network = DuelingQNetwork(self.state_size, self.action_size)
        else:
            self.q_network = QNetwork(self.state_size, self.action_size)
            self.target_network = QNetwork(self.state_size, self.action_size)

        self.target_network.load_state_dict(self.q_network.state_dict())
        self.optimizer = optim.Adam(self.q_network.parameters(), lr=self.lr)
        self.memory: Deque = deque(maxlen=self.buffer_size)
        self.total_reward = 0.0
        self.episode_count = 0

    def act(self, state: np.ndarray, explore: bool = True) -> int:
        """Select action using epsilon-greedy policy."""
        if explore and random.random() < self.epsilon:
            return random.randrange(self.action_size)

        with torch.no_grad():
            state_tensor = torch.tensor(state, dtype=torch.float32).unsqueeze(0)
            q_values = self.q_network(state_tensor)
            return torch.argmax(q_values).item()

    def remember(
        self,
        state: np.ndarray,
        action: int,
        reward: float,
        next_state: np.ndarray,
        done: bool,
    ) -> None:
        """Store experience in replay buffer."""
        self.memory.append((state, action, reward, next_state, done))

    def replay(self) -> Optional[float]:
        """Train on batch from replay buffer."""
        if len(self.memory) < self.batch_size:
            return None

        minibatch = random.sample(self.memory, self.batch_size)
        states, actions, rewards, next_states, dones = zip(*minibatch)

        states = torch.tensor(np.array(states), dtype=torch.float32)
        actions = torch.tensor(actions, dtype=torch.int64)
        rewards = torch.tensor(rewards, dtype=torch.float32)
        next_states = torch.tensor(np.array(next_states), dtype=torch.float32)
        dones = torch.tensor(dones, dtype=torch.float32)

        # Current Q values
        q_values = self.q_network(states).gather(1, actions.unsqueeze(1)).squeeze(1)

        # Target Q values (Double DQN)
        with torch.no_grad():
            next_actions = self.q_network(next_states).argmax(1)
            next_q_values = self.target_network(next_states).gather(1, next_actions.unsqueeze(1)).squeeze(1)
            targets = rewards + self.gamma * next_q_values * (1 - dones)

        # Compute loss
        loss = nn.MSELoss()(q_values, targets)

        # Optimize
        self.optimizer.zero_grad()
        loss.backward()
        torch.nn.utils.clip_grad_norm_(self.q_network.parameters(), 1.0)
        self.optimizer.step()

        # Decay epsilon
        self.epsilon = max(self.epsilon_min, self.epsilon * self.epsilon_decay)

        return loss.item()

    def update_target_network(self) -> None:
        """Soft update of target network."""
        self.target_network.load_state_dict(self.q_network.state_dict())


# ---------------------------------------------------------------------------
# Value Decomposition Networks (VDN)
# ---------------------------------------------------------------------------


class VDN:
    """Value Decomposition Network for credit assignment."""

    def __init__(self, agents: List[MARLAgent]):
        self.agents = agents

    def joint_q(self, states: List[np.ndarray], actions: List[int]) -> float:
        """Compute joint Q-value as sum of individual Q-values."""
        total_q = 0.0
        for i, agent in enumerate(self.agents):
            with torch.no_grad():
                state_tensor = torch.tensor(states[i], dtype=torch.float32).unsqueeze(0)
                q_values = agent.q_network(state_tensor)
                total_q += q_values[0, actions[i]].item()
        return total_q


# ---------------------------------------------------------------------------
# QMIX (Monotonic Value Mixing)
# ---------------------------------------------------------------------------


if TORCH_AVAILABLE:
    class QMIXMixer(nn.Module):
        """QMIX mixing network with hypernetworks."""

        def __init__(self, n_agents: int, state_size: int, embed_size: int = 64):
            super().__init__()
            self.n_agents = n_agents
            self.embed_size = embed_size

            # Hypernetworks for weights and biases
            self.hyper_w1 = nn.Linear(state_size, embed_size * n_agents)
            self.hyper_b1 = nn.Linear(state_size, embed_size)
            self.hyper_w2 = nn.Linear(state_size, embed_size)
            self.hyper_b2 = nn.Sequential(
                nn.Linear(state_size, embed_size),
                nn.ReLU(),
                nn.Linear(embed_size, 1),
            )

        def forward(self, q_values: torch.Tensor, state: torch.Tensor) -> torch.Tensor:
            """Mix individual Q-values into joint Q-value."""
            batch_size = q_values.size(0)

            # Generate mixing weights (ensure monotonicity with abs)
            w1 = torch.abs(self.hyper_w1(state)).view(batch_size, self.n_agents, self.embed_size)
            b1 = self.hyper_b1(state).view(batch_size, 1, self.embed_size)

            # First layer
            hidden = torch.relu(torch.bmm(q_values.unsqueeze(1), w1) + b1)

            # Second layer
            w2 = torch.abs(self.hyper_w2(state)).view(batch_size, self.embed_size, 1)
            b2 = self.hyper_b2(state).view(batch_size, 1, 1)

            # Output
            q_tot = torch.bmm(hidden, w2) + b2
            return q_tot.squeeze()
else:
    class QMIXMixer:
        def __init__(self, *args, **kwargs):
            _require_torch()


class QMIX:
    """QMIX algorithm for cooperative multi-agent learning."""

    def __init__(
        self,
        agents: List[MARLAgent],
        state_size: int,
        embed_size: int = 64,
        lr: float = 0.001,
    ):
        self.agents = agents
        self.mixer = QMIXMixer(len(agents), state_size, embed_size)
        self.target_mixer = QMIXMixer(len(agents), state_size, embed_size)
        self.target_mixer.load_state_dict(self.mixer.state_dict())
        self.optimizer = optim.Adam(self.mixer.parameters(), lr=lr)

    def compute_loss(
        self,
        states: List[np.ndarray],
        actions: List[int],
        reward: float,
        next_states: List[np.ndarray],
        done: bool,
        global_state: np.ndarray,
        next_global_state: np.ndarray,
    ) -> float:
        """Compute QMIX loss for joint action-value learning."""
        # Get individual Q-values
        q_values = []
        for i, agent in enumerate(self.agents):
            state_tensor = torch.tensor(states[i], dtype=torch.float32).unsqueeze(0)
            q_val = agent.q_network(state_tensor)[0, actions[i]]
            q_values.append(q_val)

        q_values = torch.stack(q_values).unsqueeze(0)
        global_state_tensor = torch.tensor(global_state, dtype=torch.float32).unsqueeze(0)

        # Mix Q-values
        q_tot = self.mixer(q_values, global_state_tensor)

        # Target Q-values
        with torch.no_grad():
            next_q_values = []
            for i, agent in enumerate(self.agents):
                next_state_tensor = torch.tensor(next_states[i], dtype=torch.float32).unsqueeze(0)
                next_q_val = agent.target_network(next_state_tensor).max(1)[0]
                next_q_values.append(next_q_val)

            next_q_values = torch.stack(next_q_values).unsqueeze(0)
            next_global_state_tensor = torch.tensor(next_global_state, dtype=torch.float32).unsqueeze(0)
            target_q_tot = self.target_mixer(next_q_values, next_global_state_tensor)

            target = reward + (0.99 * target_q_tot * (1 - done))

        # Compute loss
        loss = nn.MSELoss()(q_tot, target)

        # Optimize
        self.optimizer.zero_grad()
        loss.backward()
        self.optimizer.step()

        return loss.item()

    def update_target_networks(self) -> None:
        """Update target networks."""
        self.target_mixer.load_state_dict(self.mixer.state_dict())
        for agent in self.agents:
            agent.update_target_network()


# ---------------------------------------------------------------------------
# COMA (Counterfactual Multi-Agent Policy Gradients)
# ---------------------------------------------------------------------------


if TORCH_AVAILABLE:
    class COMACritic(nn.Module):
        """Centralized critic for COMA with counterfactual baselines."""

        def __init__(self, state_size: int, action_size: int, n_agents: int, hidden_size: int = 128):
            super().__init__()
            self.n_agents = n_agents
            self.action_size = action_size

            # Critic takes global state + all actions
            input_size = state_size + action_size * n_agents
            self.fc1 = nn.Linear(input_size, hidden_size)
            self.fc2 = nn.Linear(hidden_size, hidden_size)
            self.fc3 = nn.Linear(hidden_size, action_size)  # Q-value for each action

        def forward(self, global_state: torch.Tensor, actions: torch.Tensor) -> torch.Tensor:
            """Compute Q-values for all possible actions of the agent."""
            x = torch.cat([global_state, actions], dim=-1)
            x = torch.relu(self.fc1(x))
            x = torch.relu(self.fc2(x))
            return self.fc3(x)
else:
    class COMACritic:
        def __init__(self, *args, **kwargs):
            _require_torch()


# ---------------------------------------------------------------------------
# MAPPO (Multi-Agent PPO)
# ---------------------------------------------------------------------------


if TORCH_AVAILABLE:
    class ActorNetwork(nn.Module):
        """Policy network for MAPPO."""

        def __init__(self, obs_size: int, action_size: int, hidden_size: int = 128):
            super().__init__()
            self.fc1 = nn.Linear(obs_size, hidden_size)
            self.fc2 = nn.Linear(hidden_size, hidden_size)
            self.fc3 = nn.Linear(hidden_size, action_size)

        def forward(self, obs: torch.Tensor) -> torch.Tensor:
            x = torch.relu(self.fc1(obs))
            x = torch.relu(self.fc2(x))
            return torch.softmax(self.fc3(x), dim=-1)


    class CriticNetwork(nn.Module):
        """Value network for MAPPO (centralized)."""

        def __init__(self, global_state_size: int, hidden_size: int = 128):
            super().__init__()
            self.fc1 = nn.Linear(global_state_size, hidden_size)
            self.fc2 = nn.Linear(hidden_size, hidden_size)
            self.fc3 = nn.Linear(hidden_size, 1)

        def forward(self, global_state: torch.Tensor) -> torch.Tensor:
            x = torch.relu(self.fc1(global_state))
            x = torch.relu(self.fc2(x))
            return self.fc3(x)
else:
    class ActorNetwork:
        def __init__(self, *args, **kwargs):
            _require_torch()

    class CriticNetwork:
        def __init__(self, *args, **kwargs):
            _require_torch()


class MAPPOSwarm:
    """Multi-Agent PPO for cooperative swarm learning."""

    def __init__(
        self,
        num_agents: int,
        obs_size: int,
        action_size: int,
        global_state_size: int,
        lr: float = 3e-4,
        clip_eps: float = 0.2,
        gamma: float = 0.99,
        value_coeff: float = 0.5,
        entropy_coeff: float = 0.01,
        epochs: int = 4,
        batch_size: int = 64,
    ):
        self.num_agents = num_agents
        self.gamma = gamma
        self.clip_eps = clip_eps
        self.value_coeff = value_coeff
        self.entropy_coeff = entropy_coeff
        self.epochs = epochs
        self.batch_size = batch_size

        self.actors = [ActorNetwork(obs_size, action_size) for _ in range(num_agents)]
        self.critic = CriticNetwork(global_state_size)

        self.actor_optims = [optim.Adam(actor.parameters(), lr=lr) for actor in self.actors]
        self.critic_optim = optim.Adam(self.critic.parameters(), lr=lr)

    def get_actions(self, obs_list: List[np.ndarray]) -> Tuple[List[int], List[torch.Tensor]]:
        """Sample actions from policy."""
        actions = []
        log_probs = []

        for i, obs in enumerate(obs_list):
            obs_tensor = torch.tensor(obs, dtype=torch.float32)
            probs = self.actors[i](obs_tensor)
            dist = Categorical(probs)
            action = dist.sample()
            actions.append(action.item())
            log_probs.append(dist.log_prob(action))

        return actions, log_probs

    def compute_advantages(
        self,
        global_states: List[np.ndarray],
        rewards: List[float],
        next_global_states: List[np.ndarray],
        dones: List[bool],
    ) -> List[float]:
        """Compute GAE advantages."""
        advantages = []
        with torch.no_grad():
            for i in range(len(rewards)):
                state_tensor = torch.tensor(global_states[i], dtype=torch.float32)
                next_state_tensor = torch.tensor(next_global_states[i], dtype=torch.float32)

                value = self.critic(state_tensor).item()
                next_value = self.critic(next_state_tensor).item()

                td_error = rewards[i] + self.gamma * (1 - dones[i]) * next_value - value
                advantages.append(td_error)

        return advantages

    def update(
        self,
        obs_batch: List[List[np.ndarray]],
        actions_batch: List[List[int]],
        old_log_probs_batch: List[List[torch.Tensor]],
        advantages_batch: List[float],
        returns_batch: List[float],
        global_states_batch: List[np.ndarray],
    ) -> Dict[str, float]:
        """Update policy and value networks."""
        losses = {"actor": 0.0, "critic": 0.0, "entropy": 0.0}

        for _ in range(self.epochs):
            # Critic update
            global_states_tensor = torch.tensor(np.array(global_states_batch), dtype=torch.float32)
            returns_tensor = torch.tensor(returns_batch, dtype=torch.float32)

            values = self.critic(global_states_tensor).squeeze()
            critic_loss = nn.MSELoss()(values, returns_tensor)

            self.critic_optim.zero_grad()
            critic_loss.backward()
            self.critic_optim.step()

            losses["critic"] += critic_loss.item()

            # Actor updates
            for agent_idx in range(self.num_agents):
                actor_loss_sum = 0.0
                entropy_sum = 0.0

                for batch_idx in range(len(obs_batch)):
                    obs = torch.tensor(obs_batch[batch_idx][agent_idx], dtype=torch.float32)
                    action = actions_batch[batch_idx][agent_idx]
                    old_log_prob = old_log_probs_batch[batch_idx][agent_idx]
                    advantage = advantages_batch[batch_idx]

                    probs = self.actors[agent_idx](obs)
                    dist = Categorical(probs)
                    new_log_prob = dist.log_prob(torch.tensor(action))

                    ratio = torch.exp(new_log_prob - old_log_prob)
                    surr1 = ratio * advantage
                    surr2 = torch.clamp(ratio, 1 - self.clip_eps, 1 + self.clip_eps) * advantage

                    actor_loss = -torch.min(surr1, surr2)
                    entropy = dist.entropy()

                    actor_loss_sum += actor_loss
                    entropy_sum += entropy

                total_loss = actor_loss_sum - self.entropy_coeff * entropy_sum

                self.actor_optims[agent_idx].zero_grad()
                total_loss.backward()
                self.actor_optims[agent_idx].step()

                losses["actor"] += actor_loss_sum.item()
                losses["entropy"] += entropy_sum.item()

        # Average losses
        for key in losses:
            losses[key] /= self.epochs

        return losses


# ---------------------------------------------------------------------------
# MARL Training Coordinator
# ---------------------------------------------------------------------------


@dataclass
class MARLTrainingConfig:
    """Configuration for MARL training."""

    state_size: int = 10
    action_size: int = 4
    num_agents: int = 4
    episodes: int = 1000
    max_steps: int = 100
    algorithm: str = "dqn"  # dqn, vdn, qmix, mappo
    use_dueling: bool = True
    gamma: float = 0.99
    lr: float = 0.001


class MARLCoordinator:
    """Coordinates MARL training for MERID swarm."""

    def __init__(self, config: MARLTrainingConfig):
        self.config = config
        self.agents: List[MARLAgent] = []
        self.algorithm = None

        self._initialize_agents()

    def _initialize_agents(self) -> None:
        """Initialize MARL agents based on algorithm."""
        for i in range(self.config.num_agents):
            agent = MARLAgent(
                agent_id=f"marl_agent_{i}",
                state_size=self.config.state_size,
                action_size=self.config.action_size,
                gamma=self.config.gamma,
                lr=self.config.lr,
                use_dueling=self.config.use_dueling,
            )
            self.agents.append(agent)

        # Initialize algorithm-specific components
        if self.config.algorithm == "vdn":
            self.algorithm = VDN(self.agents)
        elif self.config.algorithm == "qmix":
            self.algorithm = QMIX(self.agents, self.config.state_size)
        elif self.config.algorithm == "mappo":
            self.algorithm = MAPPOSwarm(
                num_agents=self.config.num_agents,
                obs_size=self.config.state_size,
                action_size=self.config.action_size,
                global_state_size=self.config.state_size * self.config.num_agents,
            )

        logger.info(
            "MARL coordinator initialized: algorithm=%s, agents=%d",
            self.config.algorithm,
            self.config.num_agents,
        )

    def train_episode(self, env_step_fn) -> Dict[str, float]:
        """Train for one episode."""
        episode_reward = 0.0
        episode_loss = 0.0
        steps = 0

        # Initialize states
        states = [np.random.randn(self.config.state_size) for _ in range(self.config.num_agents)]

        for step in range(self.config.max_steps):
            # Get actions
            actions = [agent.act(states[i]) for i, agent in enumerate(self.agents)]

            # Environment step
            next_states, rewards, done = env_step_fn(states, actions)

            # Store experiences
            for i, agent in enumerate(self.agents):
                agent.remember(states[i], actions[i], rewards[i], next_states[i], done)

            # Train
            for agent in self.agents:
                loss = agent.replay()
                if loss is not None:
                    episode_loss += loss

            episode_reward += sum(rewards)
            states = next_states
            steps += 1

            if done:
                break

        # Update target networks
        for agent in self.agents:
            agent.update_target_network()

        return {
            "episode_reward": episode_reward,
            "episode_loss": episode_loss / max(steps, 1),
            "steps": steps,
        }

    def get_metrics(self) -> Dict[str, any]:
        """Get training metrics."""
        return {
            "agents": [
                {
                    "agent_id": agent.agent_id,
                    "epsilon": agent.epsilon,
                    "total_reward": agent.total_reward,
                    "episode_count": agent.episode_count,
                    "memory_size": len(agent.memory),
                }
                for agent in self.agents
            ],
            "algorithm": self.config.algorithm,
        }
