"""Integration-style tests for TelegramBotInterface command handling."""

from __future__ import annotations

from datetime import datetime
from typing import List, Tuple

import pytest

import social.telegram_bot_interface as telegram_module
import social.social_aware_quant as social_quant_module
from social.telegram_bot_interface import TelegramBotInterface, TelegramCommand


@pytest.fixture
def stub_social_dependencies(monkeypatch):
    class FakeSocialEngine:
        def __init__(self):
            self.kill_switch_reason = None

        def get_social_risk_status(self):
            return {
                "kill_switch_active": False,
                "total_exposure_usd": 12_345,
                "active_positions": 3,
                "total_exposure": 12_345,
                "data_freshness_score": 0.95,
            }

        def get_top_asset_exposures(self, limit=10):
            return [
                ("BTC", 5_000),
                ("ETH", 3_000),
            ]

        def activate_kill_switch(self, reason: str):
            self.kill_switch_reason = reason

    fake_engine = FakeSocialEngine()

    for module in (telegram_module, social_quant_module):
        monkeypatch.setattr(
            module,
            "get_social_aware_quant_engine",
            lambda: fake_engine,
            raising=False,
        )

    class FakeRiskControls:
        def get_risk_status(self):
            return {"kill_switch_active": False, "violations": []}

    monkeypatch.setattr(
        telegram_module,
        "get_multi_agent_risk_controls",
        lambda: FakeRiskControls(),
        raising=False,
    )

    class FakeHealthMonitor:
        def get_health_summary(self):
            return {"total_bots": 2}

    monkeypatch.setattr(
        telegram_module,
        "get_social_bot_health_monitor",
        lambda: FakeHealthMonitor(),
        raising=False,
    )

    return fake_engine


@pytest.fixture
def bot(monkeypatch, stub_social_dependencies):
    bot = TelegramBotInterface(
        bot_token="fake",
        authorized_users=["alice", "bob", "charlie", "abuser"],
    )
    bot._rate_limits.clear()
    return bot


@pytest.mark.asyncio
async def test_status_command_routes_correctly(bot, monkeypatch):
    cmd = TelegramCommand(
        command="status",
        args=[],
        user_id="alice",
        chat_id="room1",
        timestamp=datetime.utcnow(),
    )

    response = await bot.process_command(cmd)
    assert response is not None
    assert "System Status" in response.text
    assert "Exposure" in response.text


@pytest.mark.asyncio
async def test_rate_limiting_per_user(bot):
    def make_cmd(user: str) -> TelegramCommand:
        return TelegramCommand(
            command="status",
            args=[],
            user_id=user,
            chat_id="room1",
            timestamp=datetime.utcnow(),
        )

    for _ in range(bot._rate_limit_max):
        resp = await bot.process_command(make_cmd("abuser"))
        assert resp is not None
        assert "Rate limit" not in resp.text

    limited_resp = await bot.process_command(make_cmd("abuser"))
    assert limited_resp is not None
    assert "Rate limit" in limited_resp.text

    for _ in range(3):
        resp = await bot.process_command(make_cmd("bob"))
        assert resp is not None
        assert "Rate limit" not in resp.text


@pytest.mark.asyncio
async def test_kill_command_triggers_backend_and_alert(bot, monkeypatch, stub_social_dependencies):
    alert_calls: List[Tuple[str, str]] = []

    async def fake_send_alert(message, severity="info"):
        alert_calls.append((message, severity))

    monkeypatch.setattr(bot, "send_alert", fake_send_alert)

    cmd = TelegramCommand(
        command="kill",
        args=[],
        user_id="charlie",
        chat_id="room2",
        timestamp=datetime.utcnow(),
    )

    response = await bot.process_command(cmd)
    assert response is not None
    assert "KILL SWITCH" in response.text
    engine = stub_social_dependencies
    assert engine.kill_switch_reason == "telegram_emergency_command"
    assert alert_calls
    assert alert_calls[0][1] == "critical"
