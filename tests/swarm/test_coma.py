"""Tests for swarm.coma."""

from __future__ import annotations

import numpy as np
import pytest

torch = pytest.importorskip("torch")
torch = pytest.importorskip("torch")

from swarm.coma import (
    COMA,
    COMAAgent,
    COMACriticCentralized,
    COMATransformerCritic,
    COMA_QMIX_Hybrid,
    create_coma_swarm,
)


def _make_agent(agent_id: str) -> COMAAgent:
    torch.manual_seed(0)
    np.random.seed(0)
    return COMAAgent(agent_id=agent_id, obs_size=3, action_size=2, hidden_size=8)


def test_coma_agent_select_action_probabilities_sum_to_one():
    agent = _make_agent("a0")
    obs = np.array([0.1, -0.2, 0.3], dtype=np.float32)

    action, probs = agent.select_action(obs, explore=True)

    assert action in {0, 1}
    assert torch.isclose(probs.sum(), torch.tensor(1.0))
    assert (probs >= 0).all()


def test_coma_agent_reset_hidden_clears_cached_state():
    agent = _make_agent("a0")
    obs = np.array([0.5, 0.1, -0.3], dtype=np.float32)

    agent.select_action(obs, explore=True)
    assert agent.hidden_state is not None

    agent.reset_hidden()

    assert agent.hidden_state is None


class _FakeCritic(torch.nn.Module):
    def __init__(self, action_size: int):
        super().__init__()
        self.action_size = action_size

    def forward(self, global_state: torch.Tensor, actions: torch.Tensor, agent_idx: int) -> torch.Tensor:  # noqa: ARG002
        batch = actions.size(0)
        base = torch.arange(
            self.action_size,
            dtype=torch.float32,
            device=actions.device,
        ).unsqueeze(0)
        return base.repeat(batch, 1) + agent_idx


@pytest.fixture()
def coma_with_fake_critic():
    agents = [_make_agent("a0"), _make_agent("a1")]
    coma = COMA(agents, global_state_size=3, action_size=2, n_agents=2)
    fake = _FakeCritic(action_size=2)
    coma.critic = fake
    coma.target_critic = _FakeCritic(action_size=2)
    return coma


def test_compute_counterfactual_baseline(coma_with_fake_critic):
    coma = coma_with_fake_critic
    global_state = torch.zeros(1, 3)
    actions = torch.tensor([[0, 1]])
    policy_probs = torch.tensor([[0.25, 0.75]])

    baseline = coma.compute_counterfactual_baseline(global_state, actions, agent_idx=0, policy_probs=policy_probs)

    expected = 0.0 * 0.25 + 1.0 * 0.75
    assert torch.isclose(baseline, torch.tensor(expected)).all()


def test_compute_counterfactual_baseline_accepts_1d_probs(coma_with_fake_critic):
    coma = coma_with_fake_critic
    global_state = torch.zeros(1, 3)
    actions = torch.tensor([[1, 0]])
    policy_probs = torch.tensor([0.4, 0.6])

    baseline = coma.compute_counterfactual_baseline(global_state, actions, agent_idx=1, policy_probs=policy_probs)

    expected = 1.0 * 0.4 + 2.0 * 0.6
    assert torch.isclose(baseline, torch.tensor(expected)).all()


def test_compute_advantages_matches_q_minus_baseline(coma_with_fake_critic):
    coma = coma_with_fake_critic
    global_state = torch.zeros(1, 3)
    actions = torch.tensor([[0, 1]])
    policy_probs_list = [torch.tensor([[0.6, 0.4]]), torch.tensor([[0.3, 0.7]])]

    advantages = coma.compute_advantages(global_state, actions, policy_probs_list)

    q_agent0 = 0.0  # fake critic returns action value itself
    baseline_agent0 = 0.6 * 0.0 + 0.4 * 1.0
    assert torch.isclose(advantages[0], torch.tensor([q_agent0 - baseline_agent0])).all()

    q_agent1 = 2.0
    baseline_agent1 = 0.3 * 1.0 + 0.7 * 2.0
    assert torch.isclose(advantages[1], torch.tensor([q_agent1 - baseline_agent1])).all()


def test_update_target_network_copies_parameters():
    agents = [_make_agent("a0"), _make_agent("a1")]
    coma = COMA(agents, global_state_size=3, action_size=2, n_agents=2)
    critic: COMACriticCentralized = coma.critic  # type: ignore[assignment]
    target: COMACriticCentralized = coma.target_critic  # type: ignore[assignment]

    with torch.no_grad():
        critic.fc1.weight.fill_(2.0)
        target.fc1.weight.zero_()

    coma.update_target_network(tau=1.0)

    assert torch.allclose(target.fc1.weight, critic.fc1.weight)


def test_update_target_network_tau_partial_blends_weights():
    agents = [_make_agent("a0"), _make_agent("a1")]
    coma = COMA(agents, global_state_size=3, action_size=2, n_agents=2)
    critic: COMACriticCentralized = coma.critic  # type: ignore[assignment]
    target: COMACriticCentralized = coma.target_critic  # type: ignore[assignment]

    with torch.no_grad():
        critic.fc1.weight.fill_(4.0)
        target.fc1.weight.zero_()

    coma.update_target_network(tau=0.25)

    assert torch.allclose(target.fc1.weight, torch.full_like(target.fc1.weight, 1.0))


def test_coma_train_step_returns_metrics():
    agents = [_make_agent("a0"), _make_agent("a1")]
    coma = COMA(agents, global_state_size=3, action_size=2, n_agents=2)

    observations = [np.zeros(3, dtype=np.float32) for _ in range(2)]
    global_state = np.zeros(3, dtype=np.float32)
    actions = [0, 1]
    rewards = [1.0, 1.0]
    next_observations = [np.ones(3, dtype=np.float32) for _ in range(2)]
    next_global_state = np.ones(3, dtype=np.float32)
    next_actions = [1, 0]

    metrics = coma.train_step(
        observations,
        global_state,
        actions,
        rewards,
        next_observations,
        next_global_state,
        next_actions,
        done=False,
    )

    assert set(metrics.keys()) == {"critic_loss", "actor_loss", "avg_advantage"}


def test_coma_update_critic_and_actors_smoke():
    agents = [_make_agent("a0"), _make_agent("a1")]
    coma = COMA(agents, global_state_size=4, action_size=2, n_agents=2)

    global_states = torch.zeros(2, 4)
    actions = torch.tensor([[0, 1], [1, 0]])
    rewards = torch.tensor([1.0, 0.5])
    next_global_states = torch.ones(2, 4)
    next_actions = torch.tensor([[1, 0], [0, 1]])
    dones = torch.zeros(2)

    critic_loss = coma.update_critic(
        global_states,
        actions,
        rewards,
        next_global_states,
        next_actions,
        dones,
    )
    assert isinstance(critic_loss, float)

    obs_tensors = [torch.zeros(3), torch.ones(3)]
    policy_probs_list = []
    for obs in obs_tensors:
        with torch.no_grad():
            probs, _ = agents[0].actor(obs.unsqueeze(0))
        policy_probs_list.append(probs.squeeze(0))

    advantages = coma.compute_advantages(
        global_states[:1],
        actions[:1],
        [policy_probs_list[0], policy_probs_list[0]],
    )
    actor_loss = coma.update_actors(obs_tensors, actions[:1], advantages)
    assert isinstance(actor_loss, float)


def test_coma_transformer_critic_forward():
    critic = COMATransformerCritic(
        global_state_size=5,
        action_size=3,
        n_agents=2,
        hidden_size=16,
        n_heads=2,
        n_layers=1,
    )
    global_state = torch.randn(2, 5)
    actions = torch.randint(0, 3, (2, 2))
    q_values = critic(global_state, actions, agent_idx=1)

    assert q_values.shape == (2, 3)


def test_create_coma_swarm_variants():
    agents, coma = create_coma_swarm(
        n_agents=2,
        obs_size=3,
        action_size=2,
        global_state_size=4,
        use_transformer=True,
    )
    assert len(agents) == 2
    assert isinstance(coma.critic, COMATransformerCritic)

    agents_h, hybrid = create_coma_swarm(
        n_agents=2,
        obs_size=3,
        action_size=2,
        global_state_size=4,
        use_qmix_hybrid=True,
    )
    assert len(agents_h) == 2
    assert isinstance(hybrid.mixer, torch.nn.Module)


def test_coma_qmix_hybrid_advantages():
    agents = [_make_agent("a0"), _make_agent("a1")]
    hybrid = COMA_QMIX_Hybrid(agents, global_state_size=4, action_size=2, n_agents=2)
    global_state = torch.zeros(1, 4)
    actions = torch.tensor([[0, 1]])

    policy_probs_list = [torch.tensor([0.5, 0.5]), torch.tensor([0.4, 0.6])]
    advantages = hybrid.compute_mixed_advantages(global_state, actions, policy_probs_list)

    assert len(advantages) == 2
    assert all(isinstance(val, torch.Tensor) for val in advantages)
