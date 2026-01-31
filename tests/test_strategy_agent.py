"""Tests for guardrail-aware behavior in agents.strategy_agent."""

from __future__ import annotations

import pytest

from agents.strategy_agent import StrategyAgent


def _make_result(allowed: bool, reasons: list[str] | None = None) -> dict:
    return {
        "allowed": allowed,
        "reasons": reasons or [],
        "sizing": {"size_usd": 0},
        "constraints": {},
    }


@pytest.mark.asyncio
async def test_guardrail_blocked_intent_propagates_reason(monkeypatch):
    agent = StrategyAgent()
    blocked = _make_result(False, ["kill switch active"])

    monkeypatch.setattr(
        "agents.strategy_agent.evaluate_social_trade",
        lambda **_: blocked,
    )

    result = await agent.evaluate_social_trade(
        strategy_id="alpha",
        asset="BTC",
        portfolio_value=100_000,
        sentiment_score=0.8,
    )

    assert result is blocked
    assert result["allowed"] is False
    assert "kill switch" in result["reasons"][0]


@pytest.mark.asyncio
async def test_guardrail_warning_is_surfaced(monkeypatch):
    agent = StrategyAgent()
    warning = _make_result(True, ["data stale but acceptable"])

    monkeypatch.setattr(
        "agents.strategy_agent.evaluate_social_trade",
        lambda **_: warning,
    )

    result = await agent.evaluate_social_trade(
        strategy_id="beta",
        asset="ETH",
        portfolio_value=50_000,
        sentiment_score=0.2,
    )

    assert result is warning
    assert result["allowed"] is True
    assert result["reasons"] == ["data stale but acceptable"]


@pytest.mark.asyncio
async def test_guardrail_clear_path_passes_through(monkeypatch):
    agent = StrategyAgent()
    approved = _make_result(True)

    monkeypatch.setattr(
        "agents.strategy_agent.evaluate_social_trade",
        lambda **_: approved,
    )

    result = await agent.evaluate_social_trade(
        strategy_id="gamma",
        asset="SOL",
        portfolio_value=25_000,
        sentiment_score=0.1,
    )

    assert result is approved
    assert result["allowed"] is True
    assert result["reasons"] == []
