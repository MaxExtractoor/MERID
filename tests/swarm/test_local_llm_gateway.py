"""Tests for swarm.local_llm_gateway behaviors."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta

import pytest

from swarm import local_llm_gateway as llm


@pytest.fixture(autouse=True)
def reset_singleton(monkeypatch):
    monkeypatch.setattr(llm, "_local_llm_gateway", None)
    yield


@pytest.mark.asyncio
async def test_generate_respects_token_budget(monkeypatch):
    gateway = llm.LocalLLMGateway()
    gateway._tokens_used_today = gateway._token_budget_daily - 10

    request = llm.LLMRequest(
        request_id="req-budget",
        prompt="Hello",
        model="llama3.1",
        max_tokens=50,
        temperature=0.2,
    )

    response = await gateway.generate(request)
    assert response is None


@pytest.mark.asyncio
async def test_generate_uses_alternate_provider_when_primary_full(monkeypatch):
    gateway = llm.LocalLLMGateway()
    gateway._active_requests["ollama"] = gateway._providers["ollama"].max_concurrent

    backup = llm.ProviderConfig(
        name="custom_llama",
        endpoint="http://localhost:9000",
        models=["llama3.1"],
        priority=2,
        max_concurrent=4,
    )
    gateway.register_provider(backup)

    async def fake_call(provider, request):
        return "ok"

    monkeypatch.setattr(gateway, "_call_provider", fake_call)

    request = llm.LLMRequest(
        request_id="req-fallback",
        prompt="Hello",
        model="llama3.1",
        max_tokens=5,
        temperature=0.2,
    )

    response = await gateway.generate(request)
    assert response is not None
    assert response.provider == "custom_llama"


@pytest.mark.asyncio
async def test_request_history_trimmed_after_threshold():
    gateway = llm.LocalLLMGateway()

    async def fake_call(provider, request):
        return "response"

    gateway._call_provider = fake_call  # type: ignore[assignment]

    for idx in range(1001):
        request = llm.LLMRequest(
            request_id=f"req-{idx}",
            prompt="Hello",
            model="llama3.1",
            max_tokens=1,
            temperature=0.1,
        )
        await gateway.generate(request)

    assert len(gateway._request_history) == 500
    assert gateway._request_history[0].request_id == "req-501"


def test_get_provider_status_reflects_registration():
    gateway = llm.LocalLLMGateway()
    new_provider = llm.ProviderConfig(
        name="new-provider",
        endpoint="http://localhost:5555",
        models=["custom"],
        priority=5,
    )
    gateway.register_provider(new_provider)

    status = gateway.get_provider_status()
    assert "new-provider" in status["providers"]
    assert status["providers"]["new-provider"]["max_concurrent"] == new_provider.max_concurrent


def test_check_token_budget_resets_each_day():
    gateway = llm.LocalLLMGateway()
    gateway._last_reset = datetime.utcnow().date() - timedelta(days=1)
    gateway._tokens_used_today = gateway._token_budget_daily

    assert gateway._check_token_budget(1) is True
    assert gateway._tokens_used_today == 0


def test_check_token_budget_blocks_when_limit_exceeded():
    gateway = llm.LocalLLMGateway()
    gateway._tokens_used_today = gateway._token_budget_daily
    assert gateway._check_token_budget(1) is False


def test_select_provider_returns_none_when_no_candidates(capfd):
    gateway = llm.LocalLLMGateway()
    gateway._providers = {}

    assert gateway._select_provider("non-existent") is None


def test_select_provider_returns_first_candidate_when_all_busy():
    gateway = llm.LocalLLMGateway()
    for provider in gateway._providers.values():
        gateway._active_requests[provider.name] = provider.max_concurrent

    chosen = gateway._select_provider("llama3.1")
    assert chosen is not None
    assert chosen.name == "ollama"


@pytest.mark.asyncio
async def test_generate_returns_none_when_no_provider_available():
    gateway = llm.LocalLLMGateway()
    gateway._providers = {}

    request = llm.LLMRequest(
        request_id="req-missing",
        prompt="Hello",
        model="unknown",
        max_tokens=10,
        temperature=0.1,
    )

    assert await gateway.generate(request) is None


@pytest.mark.asyncio
async def test_generate_handles_provider_exception(monkeypatch):
    gateway = llm.LocalLLMGateway()

    async def boom(provider, request):  # pragma: no cover - ensures raising path
        raise RuntimeError("boom")

    monkeypatch.setattr(gateway, "_call_provider", boom)

    request = llm.LLMRequest(
        request_id="req-error",
        prompt="Hello",
        model="llama3.1",
        max_tokens=5,
        temperature=0.1,
    )

    assert await gateway.generate(request) is None
    assert gateway._active_requests.get("ollama", 0) == 0


@pytest.mark.asyncio
async def test_call_provider_returns_mock_response(monkeypatch):
    gateway = llm.LocalLLMGateway()

    async def fast_sleep(delay):
        return

    monkeypatch.setattr(asyncio, "sleep", fast_sleep)

    provider = gateway._providers["ollama"]
    request = llm.LLMRequest(
        request_id="req-call",
        prompt="Explain",
        model="llama3.1",
        max_tokens=1,
        temperature=0.1,
    )

    response = await gateway._call_provider(provider, request)
    assert "Mock response" in response


def test_set_token_budget_updates_status():
    gateway = llm.LocalLLMGateway()
    gateway.set_token_budget(42)
    status = gateway.get_provider_status()
    assert status["token_budget"]["daily_limit"] == 42


def test_get_local_llm_gateway_singleton(monkeypatch):
    monkeypatch.setattr(llm, "_local_llm_gateway", None)
    first = llm.get_local_llm_gateway()
    second = llm.get_local_llm_gateway()
    assert first is second
