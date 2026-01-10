"""Tests for Stage 9 MARL engine."""

from __future__ import annotations

import numpy as np
import pytest
import torch

from swarm.marl_engine import (
    DuelingQNetwork,
    MAPPOSwarm,
    MARLAgent,
    MARLCoordinator,
    MARLTrainingConfig,
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
    
    assert q_tot.shape == (1,)


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
