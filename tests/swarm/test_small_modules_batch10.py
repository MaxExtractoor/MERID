"""Tests for rllib_wrapper, sb3_wrapper, and secure_messaging modules."""

from __future__ import annotations

import sys
import types
from datetime import datetime, timedelta

import numpy as np
import pytest

from swarm.rllib_wrapper import (
    MERIDRLlibEnv,
    distributed_marl_training,
    evaluate_rllib_model,
    load_rllib_checkpoint,
    train_rllib_marl,
)
from swarm.sb3_wrapper import (
    MERIDMultiAgentEnv,
    load_sb3_model,
    train_sb3_marl,
)
from swarm.secure_messaging import MessageType, SecureMessagingProtocol


class _DummyAlgo:
    def __init__(self) -> None:
        self.train_calls = 0

    def train(self) -> dict[str, float]:
        self.train_calls += 1
        return {"episode_reward_mean": 1.0, "episode_len_mean": 5.0}

    def save(self) -> str:
        return "/tmp/checkpoint"

    def compute_single_action(self, _obs, explore: bool = False) -> int:
        return 0


class _DummyConfig:
    def __init__(self, label: str) -> None:
        self.label = label
        self.settings: dict[str, object] = {}

    def environment(self, env, env_config):
        self.settings["env"] = env
        self.settings["env_config"] = env_config
        return self

    def framework(self, framework: str):
        self.settings["framework"] = framework
        return self

    def rollouts(self, num_rollout_workers: int):
        self.settings["rollouts"] = num_rollout_workers
        return self

    def resources(self, num_gpus: int):
        self.settings["resources"] = num_gpus
        return self

    def training(self, **kwargs):
        self.settings["training"] = kwargs
        return self

    def build(self) -> _DummyAlgo:
        return _DummyAlgo()


def _make_config_class(label: str):
    class _Config(_DummyConfig):
        def __init__(self):
            super().__init__(label)

    return _Config


def _make_algo_class(label: str):
    class _Algo:
        @classmethod
        def from_checkpoint(cls, path: str):
            return {"algorithm": label, "checkpoint": path}

    return _Algo


def _install_fake_ray(monkeypatch):
    fake_ray = types.ModuleType("ray")
    fake_ray._initialized = False  # type: ignore[attr-defined]

    def is_initialized():
        return fake_ray._initialized  # type: ignore[attr-defined]

    def init(ignore_reinit_error: bool = True):
        fake_ray._initialized = True  # type: ignore[attr-defined]

    fake_ray.is_initialized = is_initialized  # type: ignore[attr-defined]
    fake_ray.init = init  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "ray", fake_ray)
    monkeypatch.setitem(sys.modules, "ray.tune", types.ModuleType("ray.tune"))

    algo_pkg = types.ModuleType("ray.rllib.algorithms")
    monkeypatch.setitem(sys.modules, "ray.rllib.algorithms", algo_pkg)

    configs = {
        "ray.rllib.algorithms.ppo": ("PPOConfig", "PPO"),
        "ray.rllib.algorithms.appo": ("APPOConfig", "APPO"),
        "ray.rllib.algorithms.impala": ("ImpalaConfig", "Impala"),
        "ray.rllib.algorithms.apex_dqn": ("ApexDQNConfig", "ApexDQN"),
    }

    for module_name, (config_name, algo_name) in configs.items():
        module = types.ModuleType(module_name)
        setattr(module, config_name, _make_config_class(algo_name))
        setattr(module, algo_name, _make_algo_class(algo_name))
        monkeypatch.setitem(sys.modules, module_name, module)


def _install_fake_sb3(monkeypatch):
    sb3_module = types.ModuleType("stable_baselines3")

    class _BaseModel:
        def __init__(self, *_args, **_kwargs):
            self.saved_path: str | None = None
            self.learned_steps = 0

        def learn(self, total_timesteps: int) -> None:
            self.learned_steps = total_timesteps

        def save(self, path: str) -> None:
            self.saved_path = path

        @classmethod
        def load(cls, path: str):
            instance = cls()
            instance.saved_path = path
            return instance

        def predict(self, _obs, deterministic: bool = True):
            return 0, None

    class _PPO(_BaseModel):
        pass

    class _DQN(_BaseModel):
        pass

    sb3_module.PPO = _PPO  # type: ignore[attr-defined]
    sb3_module.DQN = _DQN  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "stable_baselines3", sb3_module)

    env_util_module = types.ModuleType("stable_baselines3.common.env_util")

    def make_vec_env(factory, n_envs: int, vec_env_cls=None):  # pragma: no cover - simple stub
        envs = [factory() for _ in range(n_envs)]
        return {"envs": envs, "cls": vec_env_cls}

    env_util_module.make_vec_env = make_vec_env  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "stable_baselines3.common.env_util", env_util_module)

    vec_env_module = types.ModuleType("stable_baselines3.common.vec_env")
    vec_env_module.DummyVecEnv = object  # type: ignore[attr-defined]
    vec_env_module.SubprocVecEnv = object  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "stable_baselines3.common.vec_env", vec_env_module)


@pytest.fixture()
def secure_protocol() -> SecureMessagingProtocol:
    return SecureMessagingProtocol()


class TestMERIDRLlibEnv:
    def test_reset_and_step_cycle(self):
        env = MERIDRLlibEnv({"max_steps": 2, "obs_size": 20})
        obs, info = env.reset()

        assert obs.shape == (20,)
        assert info == {}

        next_obs, reward, done, truncated, step_info = env.step(0)
        assert next_obs.shape == (20,)
        assert 0.0 <= reward <= 1.0
        assert done is False
        assert truncated is False
        assert step_info["step"] == 1

        _, _, done, _, _ = env.step(1)
        assert done is True


class TestTrainRLLibMARL:
    def test_training_pipeline_uses_stub_configs(self, monkeypatch):
        _install_fake_ray(monkeypatch)

        algo = train_rllib_marl(num_agents=3, num_workers=1, num_gpus=0, training_iterations=3, algorithm="PPO")

        assert isinstance(algo, _DummyAlgo)
        assert algo.train_calls == 3

    def test_unknown_algorithm_returns_none(self, monkeypatch):
        _install_fake_ray(monkeypatch)
        assert train_rllib_marl(algorithm="UNKNOWN") is None


class TestEvaluateAndDistributedRLlib:
    def test_evaluate_rllib_model_returns_metrics(self):
        class _Algo:
            def compute_single_action(self, _obs, explore: bool = False) -> int:
                return 0

        metrics = evaluate_rllib_model(_Algo(), num_episodes=2)
        assert metrics["num_episodes"] == 2
        assert "mean_reward" in metrics

    def test_distributed_training_uses_helpers(self, monkeypatch):
        fake_algo = _DummyAlgo()
        monkeypatch.setattr("swarm.rllib_wrapper.train_rllib_marl", lambda **_: fake_algo)
        monkeypatch.setattr(
            "swarm.rllib_wrapper.evaluate_rllib_model",
            lambda algo, num_episodes: {"mean_reward": 1.23, "num_episodes": num_episodes, "algo_id": id(algo)},
        )

        result = distributed_marl_training(num_agents=10, num_workers=2, num_gpus=0, training_iterations=5)

        assert result["status"] == "success"
        assert result["metrics"]["mean_reward"] == pytest.approx(1.23)


class TestLoadRLLibCheckpoint:
    def test_loads_stub_algorithm(self, monkeypatch):
        _install_fake_ray(monkeypatch)
        loaded = load_rllib_checkpoint("/tmp/checkpoint", algorithm="PPO")
        assert loaded["checkpoint"] == "/tmp/checkpoint"

    def test_unknown_algorithm_returns_none(self, monkeypatch):
        _install_fake_ray(monkeypatch)
        assert load_rllib_checkpoint("/tmp/checkpoint", algorithm="XYZ") is None


class TestMERIDMultiAgentEnv:
    def test_step_returns_rewards_and_terminations(self):
        env = MERIDMultiAgentEnv(num_agents=3, max_steps=5)
        obs, _ = env.reset()
        actions = {agent_id: 1 for agent_id in env.agents}

        observations, rewards, terminations, truncations, infos = env.step(actions)

        assert set(observations.keys()) == set(env.agents)
        assert all(isinstance(r, float) for r in rewards.values())
        assert all(key in infos for key in env.agents)
        assert all(terminations.values())  # consensus quality 1.0 -> done
        assert not any(truncations.values())


class TestTrainSB3MARL:
    def test_trains_with_stub_sb3(self, monkeypatch):
        _install_fake_sb3(monkeypatch)
        model = train_sb3_marl(num_agents=2, total_timesteps=10, n_envs=1, algorithm="ppo")

        assert model.saved_path is not None
        assert model.learned_steps == 10

    def test_missing_dependency_returns_none(self, monkeypatch):
        import builtins

        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name.startswith("stable_baselines3"):
                raise ImportError("missing")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr("builtins.__import__", fake_import)
        assert train_sb3_marl() is None


class TestLoadSB3Model:
    def test_loads_stub_model(self, monkeypatch):
        _install_fake_sb3(monkeypatch)
        loaded = load_sb3_model("/tmp/model", algorithm="ppo")
        assert loaded.saved_path == "/tmp/model"

    def test_unknown_algorithm_returns_none(self, monkeypatch):
        _install_fake_sb3(monkeypatch)
        assert load_sb3_model("/tmp/model", algorithm="sarsa") is None


class TestSecureMessagingProtocol:
    def test_session_binding_and_signature(self, secure_protocol):
        session = secure_protocol.establish_mtls_session("client", "server", "secret")
        binding_id = secure_protocol.bind_token_to_session(session.session_id, "token")
        message = secure_protocol.create_message(
            MessageType.REQUEST,
            sender_did="agent_a",
            recipient_did="agent_b",
            payload={"cmd": "ping"},
            session_id=session.session_id,
        )

        assert message.token_binding_id == binding_id
        verified, msg = secure_protocol.verify_message(message, session.session_id)
        assert verified is True
        assert msg == "Message verified"

    def test_replay_detection_blocks_duplicate(self, secure_protocol):
        session = secure_protocol.establish_mtls_session("client", "server", "secret")
        secure_protocol.bind_token_to_session(session.session_id, "token")
        message = secure_protocol.create_message(
            MessageType.EVENT,
            sender_did="agent_a",
            recipient_did="agent_b",
            payload={"event": "update"},
            session_id=session.session_id,
        )

        first_verify, _ = secure_protocol.verify_message(message, session.session_id)
        assert first_verify is True
        second_verify, error = secure_protocol.verify_message(message, session.session_id)
        assert second_verify is False
        assert "Replay" in error

    def test_send_and_receive_audit_logs(self, secure_protocol):
        session = secure_protocol.establish_mtls_session("client", "server", "secret")
        secure_protocol.bind_token_to_session(session.session_id, "token")
        outbound = secure_protocol.create_message(
            MessageType.RESPONSE,
            sender_did="agent_a",
            recipient_did="agent_b",
            payload={"status": "ok"},
            session_id=session.session_id,
        )

        send_log = secure_protocol.send_message(outbound, session.session_id)
        assert send_log.status == "sent"

        inbound = secure_protocol.create_message(
            MessageType.RESPONSE,
            sender_did="agent_b",
            recipient_did="agent_a",
            payload={"status": "ok"},
            session_id=session.session_id,
        )

        delivered, reason, payload = secure_protocol.receive_message(inbound, session.session_id)
        assert delivered is True
        assert reason == "Message received"
        assert payload == {"status": "ok"}

    def test_bind_token_missing_session_raises(self, secure_protocol):
        with pytest.raises(ValueError):
            secure_protocol.bind_token_to_session("missing", "token")

    def test_message_too_old_rejected(self, secure_protocol):
        session = secure_protocol.establish_mtls_session("client", "server", "secret")
        message = secure_protocol.create_message(
            MessageType.ERROR,
            sender_did="agent_a",
            recipient_did="agent_b",
            payload={"error": "stale"},
            session_id=session.session_id,
        )
        message.timestamp = datetime.utcnow() - timedelta(hours=1)
        verified, reason = secure_protocol.verify_message(message, session.session_id)
        assert verified is False
        assert "too old" in reason
