"""Tests for Stage 9 MARL engine."""

from __future__ import annotations

import numpy as np
import pytest

torch = pytest.importorskip("torch")

from swarm.marl_engine import (
    COMACritic,
    DuelingQNetwork,
    MAPPOSwarm,
    MARLAgent,
    MARLCoordinator,
    MARLTrainingConfig,
    QMIX,
    QMIXMixer,
    QNetwork,
    VDN,
)


def test_q_network_forward():
    """Test Q-network forward pass."""
    state_size = 10
    action_size = 4
    q_net = QNetwork(state_size, action_size)
    
    state = torch.randn(1, state_size)
    q_values = q_net(state)
    
    assert q_values.shape == (1, action_size)


def test_dueling_q_network_forward():
    """Test dueling Q-network forward pass."""
    state_size = 10
    action_size = 4
    q_net = DuelingQNetwork(state_size, action_size)
    
    state = torch.randn(1, state_size)
    q_values = q_net(state)
    
    assert q_values.shape == (1, action_size)


def test_marl_agent_initialization():
    """Test MARL agent initialization."""
    agent = MARLAgent(
        agent_id="test_agent",
        state_size=10,
        action_size=4,
        use_dueling=True,
    )
    
    assert agent.agent_id == "test_agent"
    assert agent.epsilon == 1.0
    assert len(agent.memory) == 0
    assert isinstance(agent.q_network, DuelingQNetwork)


def test_marl_agent_act():
    """Test MARL agent action selection."""
    agent = MARLAgent(
        agent_id="test_agent",
        state_size=10,
        action_size=4,
        epsilon=0.0,  # No exploration
    )
    
    state = np.random.randn(10)
    action = agent.act(state, explore=False)
    
    assert isinstance(action, int)
    assert 0 <= action < 4


def test_marl_agent_remember():
    """Test MARL agent experience storage."""
    agent = MARLAgent(
        agent_id="test_agent",
        state_size=10,
        action_size=4,
    )
    
    state = np.random.randn(10)
    next_state = np.random.randn(10)
    agent.remember(state, 1, 0.5, next_state, False)
    
    assert len(agent.memory) == 1


def test_marl_agent_replay():
    """Test MARL agent replay training."""
    agent = MARLAgent(
        agent_id="test_agent",
        state_size=10,
        action_size=4,
        batch_size=32,
    )
    
    # Fill memory with experiences
    for _ in range(100):
        state = np.random.randn(10)
        next_state = np.random.randn(10)
        action = np.random.randint(0, 4)
        reward = np.random.randn()
        agent.remember(state, action, reward, next_state, False)
    
    # Train
    loss = agent.replay()
    
    assert loss is not None
    assert isinstance(loss, float)
    assert agent.epsilon < 1.0  # Epsilon should decay


def test_marl_agent_replay_returns_none_when_memory_small():
    agent = MARLAgent(
        agent_id="test_agent",
        state_size=6,
        action_size=3,
        batch_size=32,
    )

    # Memory smaller than batch size
    for _ in range(10):
        state = np.random.randn(6)
        agent.remember(state, 0, 0.0, state, False)

    assert agent.replay() is None


def test_vdn_joint_q():
    """Test VDN joint Q-value computation."""
    agents = [
        MARLAgent(agent_id=f"agent_{i}", state_size=10, action_size=4)
        for i in range(3)
    ]
    
    vdn = VDN(agents)
    
    states = [np.random.randn(10) for _ in range(3)]
    actions = [0, 1, 2]
    
    joint_q = vdn.joint_q(states, actions)
    
    assert isinstance(joint_q, float)


def test_qmix_mixer_forward():
    """Test QMIX mixer forward pass."""
    n_agents = 3
    state_size = 10
    mixer = QMIXMixer(n_agents, state_size)
    
    q_values = torch.randn(1, n_agents)
    global_state = torch.randn(1, state_size)
    
    q_tot = mixer(q_values, global_state)
    # The mixer squeezes to a scalar; ensure it's 0-d or 1-d with single entry
    assert q_tot.numel() == 1
    _ = q_tot.item()


def test_qmix_compute_loss_and_update_targets(monkeypatch):
    agents = [
        MARLAgent(agent_id=f"agent_{i}", state_size=4, action_size=2, use_dueling=False)
        for i in range(2)
    ]
    qmix = QMIX(agents, state_size=4, embed_size=8)

    def simple_forward(self, q_values, state):
        return q_values.sum()

    monkeypatch.setattr(qmix.mixer, "forward", simple_forward.__get__(qmix.mixer, type(qmix.mixer)))
    monkeypatch.setattr(qmix.target_mixer, "forward", simple_forward.__get__(qmix.target_mixer, type(qmix.target_mixer)))

    states = [np.ones(4) * i for i in range(2)]
    next_states = [np.ones(4) * (i + 1) for i in range(2)]
    global_state = np.ones(4)
    next_global_state = np.ones(4) * 2
    actions = [0, 1]

    loss = qmix.compute_loss(
        states=states,
        actions=actions,
        reward=1.0,
        next_states=next_states,
        done=False,
        global_state=global_state,
        next_global_state=next_global_state,
    )

    assert isinstance(loss, float)

    # Ensure update call propagates without errors and adjusts target mixer
    before = [param.clone() for param in qmix.target_mixer.parameters()]
    with torch.no_grad():
        for param in qmix.mixer.parameters():
            param.add_(0.01)
    qmix.update_target_networks()
    after = list(qmix.target_mixer.parameters())
    assert any(not torch.allclose(b, a) for b, a in zip(before, after))


def test_mappo_swarm_initialization():
    """Test MAPPO swarm initialization."""
    mappo = MAPPOSwarm(
        num_agents=3,
        obs_size=10,
        action_size=4,
        global_state_size=30,
    )
    
    assert len(mappo.actors) == 3
    assert len(mappo.actor_optims) == 3


def test_mappo_get_actions():
    """Test MAPPO action sampling."""
    mappo = MAPPOSwarm(
        num_agents=3,
        obs_size=10,
        action_size=4,
        global_state_size=30,
    )
    
    obs_list = [np.random.randn(10) for _ in range(3)]
    actions, log_probs = mappo.get_actions(obs_list)
    
    assert len(actions) == 3
    assert len(log_probs) == 3
    assert all(isinstance(a, int) for a in actions)


def test_marl_coordinator_initialization():
    """Test MARL coordinator initialization."""
    config = MARLTrainingConfig(
        state_size=10,
        action_size=4,
        num_agents=3,
        algorithm="dqn",
    )
    
    coordinator = MARLCoordinator(config)
    
    assert len(coordinator.agents) == 3
    assert coordinator.config.algorithm == "dqn"


def test_marl_coordinator_vdn():
    """Test MARL coordinator with VDN algorithm."""
    config = MARLTrainingConfig(
        state_size=10,
        action_size=4,
        num_agents=3,
        algorithm="vdn",
    )
    
    coordinator = MARLCoordinator(config)
    
    assert coordinator.algorithm is not None
    assert isinstance(coordinator.algorithm, VDN)


def test_marl_coordinator_metrics():
    """Test MARL coordinator metrics."""
    config = MARLTrainingConfig(
        state_size=10,
        action_size=4,
        num_agents=3,
        algorithm="dqn",
    )
    
    coordinator = MARLCoordinator(config)
    metrics = coordinator.get_metrics()
    
    assert "agents" in metrics
    assert "algorithm" in metrics
    assert len(metrics["agents"]) == 3


def test_marl_agent_target_network_update():
    """Test target network update."""
    agent = MARLAgent(
        agent_id="test_agent",
        state_size=10,
        action_size=4,
    )
    
    # Get initial target network params
    initial_params = list(agent.target_network.parameters())[0].clone()
    
    # Modify q_network
    with torch.no_grad():
        for param in agent.q_network.parameters():
            param.add_(torch.randn_like(param) * 0.1)
    
    # Update target network
    agent.update_target_network()
    
    # Check that target network was updated
    updated_params = list(agent.target_network.parameters())[0]
    assert not torch.allclose(initial_params, updated_params)


def test_epsilon_decay():
    """Test epsilon decay over multiple replays."""
    agent = MARLAgent(
        agent_id="test_agent",
        state_size=10,
        action_size=4,
        epsilon=1.0,
        epsilon_decay=0.99,
        batch_size=32,
    )
    
    # Fill memory
    for _ in range(100):
        state = np.random.randn(10)
        next_state = np.random.randn(10)
        agent.remember(state, 0, 0.0, next_state, False)
    
    initial_epsilon = agent.epsilon
    
    # Train multiple times
    for _ in range(10):
        agent.replay()
    
    assert agent.epsilon < initial_epsilon
    assert agent.epsilon >= agent.epsilon_min


def test_marl_agent_exploration_vs_exploitation():
    """Test that agent explores when epsilon is high and exploits when low."""
    agent = MARLAgent(
        agent_id="test_agent",
        state_size=10,
        action_size=4,
    )
    
    state = np.random.randn(10)
    
    # High epsilon: should explore (random actions)
    agent.epsilon = 1.0
    actions_explore = [agent.act(state, explore=True) for _ in range(100)]
    unique_explore = len(set(actions_explore))
    
    # Low epsilon: should exploit (consistent actions)
    agent.epsilon = 0.0
    actions_exploit = [agent.act(state, explore=False) for _ in range(100)]
    unique_exploit = len(set(actions_exploit))
    
    # Exploration should have more variety
    assert unique_explore >= unique_exploit


def test_double_dqn_target_computation():
    """Test that agent uses Double DQN for target computation."""
    agent = MARLAgent(
        agent_id="test_agent",
        state_size=10,
        action_size=4,
        batch_size=32,
    )
    
    # Fill memory
    for _ in range(100):
        state = np.random.randn(10)
        next_state = np.random.randn(10)
        agent.remember(state, 0, 1.0, next_state, False)
    
    # Train should not raise errors
    loss = agent.replay()
    assert loss is not None


def test_coma_critic_forward_vectorized():
    critic = COMACritic(state_size=4, action_size=2, n_agents=2)

    global_state = torch.randn(3, 4)
    actions = torch.randn(3, 4)  # Already one-hot concatenated representation

    q_values = critic(global_state, actions)

    assert q_values.shape == (3, 2)


def test_mappo_compute_advantages_handles_terminal_transition():
    mappo = MAPPOSwarm(
        num_agents=2,
        obs_size=4,
        action_size=3,
        global_state_size=8,
    )

    global_states = [np.zeros(8), np.ones(8)]
    next_global_states = [np.ones(8), np.ones(8) * 2]
    rewards = [1.0, 0.5]
    dones = [False, True]

    advantages = mappo.compute_advantages(global_states, rewards, next_global_states, dones)

    assert len(advantages) == 2
    assert all(isinstance(val, float) for val in advantages)


def test_mappo_update_runs_single_epoch():
    num_agents = 2
    obs_size = 4
    global_state_size = 8

    mappo = MAPPOSwarm(
        num_agents=num_agents,
        obs_size=obs_size,
        action_size=3,
        global_state_size=global_state_size,
        epochs=1,
    )

    batch_len = 2
    obs_batch = [
        [np.random.randn(obs_size) for _ in range(num_agents)]
        for _ in range(batch_len)
    ]
    actions_batch = [
        [np.random.randint(0, 3) for _ in range(num_agents)]
        for _ in range(batch_len)
    ]
    global_states_batch = [np.random.randn(global_state_size) for _ in range(batch_len)]
    returns_batch = [1.0, 0.5]
    advantages_batch = [0.2, -0.1]

    old_log_probs_batch = []
    for b in range(batch_len):
        agent_logs = []
        for agent_idx in range(num_agents):
            obs_tensor = torch.tensor(obs_batch[b][agent_idx], dtype=torch.float32)
            probs = mappo.actors[agent_idx](obs_tensor)
            dist = torch.distributions.Categorical(probs)
            action_tensor = torch.tensor(actions_batch[b][agent_idx])
            agent_logs.append(dist.log_prob(action_tensor))
        old_log_probs_batch.append(agent_logs)

    losses = mappo.update(
        obs_batch=obs_batch,
        actions_batch=actions_batch,
        old_log_probs_batch=old_log_probs_batch,
        advantages_batch=advantages_batch,
        returns_batch=returns_batch,
        global_states_batch=global_states_batch,
    )

    assert set(losses.keys()) == {"actor", "critic", "entropy"}


def test_marl_coordinator_qmix_initialization():
    config = MARLTrainingConfig(
        state_size=6,
        action_size=3,
        num_agents=2,
        algorithm="qmix",
    )

    coordinator = MARLCoordinator(config)

    assert isinstance(coordinator.algorithm, QMIX)


def test_marl_coordinator_mappo_initialization():
    config = MARLTrainingConfig(
        state_size=6,
        action_size=3,
        num_agents=2,
        algorithm="mappo",
    )

    coordinator = MARLCoordinator(config)

    assert isinstance(coordinator.algorithm, MAPPOSwarm)


def test_marl_coordinator_train_episode_runs(monkeypatch):
    config = MARLTrainingConfig(
        state_size=2,
        action_size=2,
        num_agents=2,
        max_steps=3,
        algorithm="dqn",
    )
    coordinator = MARLCoordinator(config)

    call_counts = {"act": 0, "replay": 0, "update": 0}

    def fake_act(self, _state, explore=True):  # noqa: ARG001
        call_counts["act"] += 1
        return 0

    def fake_replay(self):
        call_counts["replay"] += 1
        return 0.1

    def fake_remember(self, *_args, **_kwargs):  # pragma: no cover - simple stub
        return None

    def fake_update(self):
        call_counts["update"] += 1

    monkeypatch.setattr(MARLAgent, "act", fake_act, raising=False)
    monkeypatch.setattr(MARLAgent, "replay", fake_replay, raising=False)
    monkeypatch.setattr(MARLAgent, "remember", fake_remember, raising=False)
    monkeypatch.setattr(MARLAgent, "update_target_network", fake_update, raising=False)

    def env_step_fn(states, actions):  # noqa: ARG001
        next_states = [np.array(state) + 1 for state in states]
        rewards = [1.0 for _ in actions]
        done = True
        return next_states, rewards, done

    result = coordinator.train_episode(env_step_fn)

    assert set(result.keys()) == {"episode_reward", "episode_loss", "steps"}
    assert call_counts["act"] > 0
    assert call_counts["replay"] > 0
    assert call_counts["update"] == config.num_agents
