"""Tests for the multi-provider LLM gateway."""

from __future__ import annotations

import asyncio
from decimal import Decimal

import pytest

from swarm import llm_gateway as llm


@pytest.fixture(autouse=True)
def deterministic_time(monkeypatch: pytest.MonkeyPatch) -> None:
    """Control time-based IDs and latency calculations."""

    fake_time = 1.0

    def fake_time_func() -> float:
        nonlocal fake_time
        fake_time += 0.01
        return fake_time

    class _DeterministicDatetime(llm.datetime):  # type: ignore[misc]
        @classmethod
        def utcnow(cls):  # type: ignore[override]
            return llm.datetime(2024, 1, 1)  # type: ignore[misc]

    monkeypatch.setattr(llm, "time", type("_T", (), {"time": fake_time_func}))
    monkeypatch.setattr(llm, "datetime", _DeterministicDatetime)


@pytest.fixture()
def gateway(monkeypatch: pytest.MonkeyPatch) -> llm.LLMGateway:
    monkeypatch.setattr(llm, "_llm_gateway", None)
    return llm.LLMGateway()


@pytest.mark.asyncio
async def test_generate_enforces_policy_and_records_usage(gateway: llm.LLMGateway) -> None:
    request = llm.LLMRequest(
        request_id="req-1",
        prompt="Summarize blockchain data",
        preferred_provider=llm.LLMProvider.OPENAI,
        data_classification=llm.DataClassification.INTERNAL,
    )

    response = await gateway.generate(request)

    assert response.provider_type == llm.LLMProvider.OPENAI
    assert response.total_tokens == response.input_tokens + response.output_tokens

    stats = gateway.get_provider_stats()
    assert stats["providers"]["openai"]["requests"] == 1
    assert stats["requests"]["total"] == 1


def test_select_provider_prefers_local_for_restricted_data(gateway: llm.LLMGateway) -> None:
    policy = gateway._policies["default"]
    request = llm.LLMRequest(
        request_id="req-sensitive",
        prompt="Private key 0xdeadbeef",
        data_classification=llm.DataClassification.RESTRICTED,
    )

    provider = gateway.select_provider(request, policy)

    assert provider is not None
    assert provider.provider_type in {llm.LLMProvider.LOCAL_LLAMA, llm.LLMProvider.LOCAL_GEMMA}


@pytest.mark.asyncio
async def test_generate_rejects_disallowed_classification(gateway: llm.LLMGateway) -> None:
    policy = gateway._policies["default"]
    policy.max_data_classification = llm.DataClassification.PUBLIC

    request = llm.LLMRequest(
        request_id="req-high",
        prompt="Confidential data",
        data_classification=llm.DataClassification.CONFIDENTIAL,
    )

    with pytest.raises(ValueError, match="exceeds policy limit"):
        await gateway.generate(request)


def test_register_provider_records_custom_config(gateway: llm.LLMGateway) -> None:
    config = gateway.register_provider(
        provider_type=llm.LLMProvider.GOOGLE,
        api_endpoint="https://fake",
        api_key="sk-test",
        available_models=["gemini"],
        default_model="gemini",
        allowed_data_classifications=[llm.DataClassification.PUBLIC],
        max_context_tokens=1234,
        data_residency_region="eu",
        cost_per_1k_input_tokens=Decimal("0.02"),
        cost_per_1k_output_tokens=Decimal("0.08"),
    )

    assert gateway._providers[config.provider_id] is config
    assert config.data_residency_region == "eu"
