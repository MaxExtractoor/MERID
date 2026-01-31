"""Batch 13 tests covering mev_rewards, network_policy, and orchestrator modules."""

from __future__ import annotations

from datetime import datetime as real_datetime, timedelta
from decimal import Decimal
from typing import Any, Set

import pytest

from swarm.mev_rewards import (
    MEVCategory,
    MEVRewardSystem,
    MEVType,
)
from swarm.network_policy import (
    ComplianceStatus,
    NetworkPolicyManager,
    ProxyType,
)
from swarm.orchestrator import (
    AgentRole,
    ModelCapability,
    ModelInterface,
    SwarmOrchestrator,
)


@pytest.fixture()
def deterministic_mev_datetime(monkeypatch):
    class _DeterministicDatetime(real_datetime):
        current = real_datetime(2026, 1, 1, 0, 0, 0)

        @classmethod
        def utcnow(cls):
            value = cls.current
            cls.current = value + timedelta(seconds=1)
            return value

    monkeypatch.setattr("swarm.mev_rewards.datetime", _DeterministicDatetime)
    return _DeterministicDatetime


@pytest.fixture()
def mev_system(deterministic_mev_datetime) -> MEVRewardSystem:
    return MEVRewardSystem()


class TestMEVRewardSystem:
    def test_record_action_updates_actor_stats(self, mev_system: MEVRewardSystem):
        action = mev_system.record_mev_action(
            actor_id="arb_1",
            mev_type=MEVType.ARBITRAGE,
            block_number=1,
            transaction_hash="0xabc",
            profit_usd=Decimal("100"),
            user_impact_usd=Decimal("5"),
            spread_improvement_bps=2.0,
        )
        assert action.mev_category is MEVCategory.SAFE
        stats = mev_system.get_actor_stats("arb_1")
        assert stats.safe_actions == 1
        assert stats.total_profit_usd == Decimal("100")
        assert stats.total_health_score > 0

    def test_calculate_reward_safe_vs_harmful(self, mev_system: MEVRewardSystem):
        safe_action = mev_system.record_mev_action(
            actor_id="arb_safe",
            mev_type=MEVType.ARBITRAGE,
            block_number=2,
            transaction_hash="0xsafe",
            profit_usd=Decimal("50"),
            spread_improvement_bps=1.0,
        )
        harmful_action = mev_system.record_mev_action(
            actor_id="sandwich",
            mev_type=MEVType.SANDWICH,
            block_number=3,
            transaction_hash="0xbad",
            profit_usd=Decimal("80"),
            user_impact_usd=Decimal("-10"),
        )
        safe_result = mev_system.calculate_reward(safe_action.action_id)
        harmful_result = mev_system.calculate_reward(harmful_action.action_id)
        assert safe_result.total_reward > Decimal("0")
        assert harmful_result.total_reward <= Decimal("0")

    def test_distribute_rewards_updates_pool(self, mev_system: MEVRewardSystem):
        action1 = mev_system.record_mev_action(
            actor_id="actor_a",
            mev_type=MEVType.BACKRUN,
            block_number=4,
            transaction_hash="0x1",
            profit_usd=Decimal("40"),
        )
        action2 = mev_system.record_mev_action(
            actor_id="actor_b",
            mev_type=MEVType.LIQUIDATION,
            block_number=5,
            transaction_hash="0x2",
            profit_usd=Decimal("60"),
        )
        pool_id = next(iter(mev_system._reward_pools))  # noqa: SLF001 - deterministic test access
        mev_system.calculate_reward(action1.action_id, pool_id)
        mev_system.calculate_reward(action2.action_id, pool_id)
        pool_before = mev_system._reward_pools[pool_id].remaining  # noqa: SLF001
        payouts = mev_system.distribute_rewards(pool_id, [action1.action_id, action2.action_id])
        pool_after = mev_system._reward_pools[pool_id].remaining  # noqa: SLF001
        assert set(payouts.keys()) == {"actor_a", "actor_b"}
        assert pool_after < pool_before

    def test_update_health_metrics_adjusts_overall_score(self, mev_system: MEVRewardSystem):
        metrics = mev_system.update_health_metrics(
            average_depth_usd=Decimal("200000"),
            average_spread_bps=5.0,
            average_slippage_bps=2.0,
            failure_rate=0.0,
            liquidation_quality_score=0.8,
        )
        assert metrics.overall_health_score >= 0.8


@pytest.fixture()
def network_manager() -> NetworkPolicyManager:
    return NetworkPolicyManager()


class TestNetworkPolicyManager:
    def test_select_proxy_prefers_low_latency(self, network_manager: NetworkPolicyManager):
        network_manager.register_proxy(
            endpoint_id="test_fast",
            endpoint_type=ProxyType.HTTPS,
            host="fast.example.com",
            port=443,
            protocol="https",
            provider="fast",
            region="US",
            latency_ms=10.0,
        )
        network_manager.register_proxy(
            endpoint_id="test_slow",
            endpoint_type=ProxyType.HTTPS,
            host="slow.example.com",
            port=443,
            protocol="https",
            provider="slow",
            region="US",
            latency_ms=80.0,
        )
        network_manager.create_policy(
            policy_id="latency_policy",
            policy_name="Low Latency",
            sensitivity_level=network_manager.get_policy("public_data").sensitivity_level,
            allowed_proxy_types={ProxyType.HTTPS},
            allowed_proxy_ids={"test_fast", "test_slow"},
            fallback_to_direct=True,
            max_latency_ms=200.0,
        )
        proxy = network_manager.select_proxy("latency_policy", user_region="US")
        assert proxy and proxy.endpoint_id == "test_fast"

    def test_select_proxy_fallback_to_direct(self, network_manager: NetworkPolicyManager):
        network_manager.create_policy(
            policy_id="fallback_policy",
            policy_name="Fallback",
            sensitivity_level=network_manager.get_policy("public_data").sensitivity_level,
            allowed_proxy_types=set(),
            allowed_proxy_ids=set(),
            fallback_to_direct=True,
        )
        proxy = network_manager.select_proxy("fallback_policy", user_region="EU")
        assert proxy and proxy.endpoint_id == "direct"

    def test_compliance_checks_cover_states(self, network_manager: NetworkPolicyManager):
        network_manager.add_geo_rule(
            rule_id="eu_rule",
            rule_name="EU",
            applies_to_regions={"EU"},
            blocked_venues={"blocked_ex"},
            allowed_venues={"kraken"},
        )
        compliant, notes = network_manager.check_compliance("EU", "kraken")
        assert compliant is ComplianceStatus.COMPLIANT
        assert "Compliant" in notes[-1]
        restricted, notes = network_manager.check_compliance("EU", "unknown_ex")
        assert restricted is ComplianceStatus.RESTRICTED
        non_compliant, notes = network_manager.check_compliance("EU", "blocked_ex")
        assert non_compliant is ComplianceStatus.NON_COMPLIANT

    def test_request_completion_updates_metrics_and_alerts(self, network_manager: NetworkPolicyManager):
        request = network_manager.create_request(
            agent_id="agent_x",
            target_url="https://api.merid",
            method="GET",
            policy_id="public_data",
            user_region="LATAM",
        )
        network_manager.complete_request(
            request_id=request.request_id,
            success=False,
            status_code=500,
            latency_ms=6000.0,
            error_message="timeout",
        )
        proxy = network_manager.get_proxy(request.proxy_id or "direct")
        assert proxy.total_requests >= 1
        alerts = network_manager.get_active_alerts(alert_type="high_latency")
        assert alerts and alerts[0].metric_value == pytest.approx(6000.0)


class _DummyInterface(ModelInterface):
    def generate(self, prompt: str, max_tokens: int = 1000, temperature: float = 0.7) -> tuple[str, float]:
        return f"response:{prompt[:20]}", 0.95

    def classify(self, text: str, labels: list[str]) -> tuple[str, float]:
        return labels[0] if labels else "", 0.9

    def get_capabilities(self) -> Set[ModelCapability]:
        return {ModelCapability.REASONING}


@pytest.fixture()
def orchestrator() -> SwarmOrchestrator:
    orch = SwarmOrchestrator()
    orch.register_model_interface("local_llama", _DummyInterface())
    return orch


class TestSwarmOrchestrator:
    def test_execute_task_success_with_registered_interface(self, orchestrator: SwarmOrchestrator):
        orchestrator.register_agent(
            agent_id="test_agent",
            agent_role=AgentRole.COORDINATOR,
            required_capabilities={ModelCapability.REASONING},
            preferred_providers=["local_llama"],
            allowed_tools=set(),
        )
        task = orchestrator.create_task(
            agent_id="test_agent",
            task_type="diagnostics",
            description="Ensure orchestration works",
        )
        result = orchestrator.execute_task(task.task_id)
        assert result.success is True
        assert result.result and "response" in result.result

    def test_execute_task_without_interface_sets_error(self, orchestrator: SwarmOrchestrator):
        orchestrator.register_model_provider(
            provider_id="no_iface",
            provider_name="No Interface",
            provider_type="local",
            capabilities={ModelCapability.REASONING},
            avg_latency_ms=20.0,
        )
        orchestrator.register_agent(
            agent_id="no_iface_agent",
            agent_role=AgentRole.COORDINATOR,
            required_capabilities={ModelCapability.REASONING},
            preferred_providers=["no_iface"],
            allowed_tools=set(),
        )
        task = orchestrator.create_task(
            agent_id="no_iface_agent",
            task_type="analysis",
            description="Should fail due to missing interface",
        )
        result = orchestrator.execute_task(task.task_id)
        assert result.success is False
        assert "No interface" in (result.error_message or "")

    def test_select_model_provider_prefers_low_latency(self, orchestrator: SwarmOrchestrator):
        orchestrator.register_model_provider(
            provider_id="fast_provider",
            provider_name="Fast",
            provider_type="local",
            capabilities={ModelCapability.REASONING},
            avg_latency_ms=5.0,
        )
        orchestrator.register_model_provider(
            provider_id="slow_provider",
            provider_name="Slow",
            provider_type="local",
            capabilities={ModelCapability.REASONING},
            avg_latency_ms=200.0,
        )
        orchestrator.register_agent(
            agent_id="latency_agent",
            agent_role=AgentRole.COORDINATOR,
            required_capabilities={ModelCapability.REASONING},
            preferred_providers=["slow_provider", "fast_provider"],
            allowed_tools=set(),
        )
        provider = orchestrator.select_model_provider("latency_agent", prefer_low_latency=True)
        assert provider and provider.provider_id == "fast_provider"
