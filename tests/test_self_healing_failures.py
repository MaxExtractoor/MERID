"""Self-healing social layer failure handling tests."""

from __future__ import annotations

from typing import List, Tuple
import sys
import types

import pytest


if "core.environment_flags" not in sys.modules:
    env_module = types.ModuleType("core.environment_flags")

    class EnvironmentFlags:  # pragma: no cover - stub
        def __init__(self) -> None:
            self.online = True

    def get_environment_flags():  # pragma: no cover - stub
        return EnvironmentFlags()

    env_module.EnvironmentFlags = EnvironmentFlags
    env_module.get_environment_flags = get_environment_flags
    sys.modules["core.environment_flags"] = env_module


import social.self_healing_social_layer as healing_module
import social.x_bot_interface as x_bot_module
import social.telegram_bot_interface as telegram_module
import social.social_aware_quant as quant_module
from social.self_healing_social_layer import SelfHealingSocialLayer


@pytest.mark.asyncio
async def test_x_bot_failure_triggers_reconnect_and_backoff(monkeypatch):
    layer = SelfHealingSocialLayer()

    class FlakyXBot:
        def __init__(self) -> None:
            self.reconnect_calls: List[str] = []

        async def reconnect(self) -> None:
            self.reconnect_calls.append("call")
            if len(self.reconnect_calls) < 3:
                raise RuntimeError("reconnect failed")

    x_bot = FlakyXBot()
    sleep_durations: List[float] = []

    async def fake_sleep(duration: float) -> None:
        sleep_durations.append(duration)

    monkeypatch.setattr(
        x_bot_module,
        "get_x_bot_service",
        lambda: x_bot,
        raising=False,
    )
    monkeypatch.setattr(healing_module.asyncio, "sleep", fake_sleep)

    result = await layer._recover_x_bot("x_bot", ["network outage"])

    assert result is True
    assert len(x_bot.reconnect_calls) == 3
    assert sleep_durations == [2.0, 4.0]


@pytest.mark.asyncio
async def test_telegram_bot_failure_triggers_restart(monkeypatch):
    layer = SelfHealingSocialLayer()

    class FlakyTelegramBot:
        def __init__(self) -> None:
            self.start_calls: List[str] = []

        async def start(self) -> None:
            self.start_calls.append("call")
            if len(self.start_calls) < 3:
                raise RuntimeError("start failed")

    telegram_bot = FlakyTelegramBot()
    sleep_durations: List[float] = []

    async def fake_sleep(duration: float) -> None:
        sleep_durations.append(duration)

    monkeypatch.setattr(
        telegram_module,
        "get_telegram_bot",
        lambda: telegram_bot,
        raising=False,
    )
    monkeypatch.setattr(healing_module.asyncio, "sleep", fake_sleep)

    result = await layer._recover_telegram_bot("telegram_bot", ["bot offline"])

    assert result is True
    assert len(telegram_bot.start_calls) == 3
    assert sleep_durations == [1.0, 2.0]


@pytest.mark.asyncio
async def test_social_feed_staleness_escalates(monkeypatch):
    layer = SelfHealingSocialLayer()

    class BrokenSocialEngine:
        def reset_state(self) -> None:
            raise RuntimeError("cache corrupted")

    monkeypatch.setattr(
        quant_module,
        "get_social_aware_quant_engine",
        lambda: BrokenSocialEngine(),
        raising=False,
    )

    alerts: List[Tuple[str, str]] = []

    class AlertOnlyTelegram:
        async def send_alert(self, message: str, severity: str = "info") -> None:
            alerts.append((message, severity))

    monkeypatch.setattr(
        telegram_module,
        "get_telegram_bot",
        lambda: AlertOnlyTelegram(),
        raising=False,
    )

    await layer._initiate_healing("social_feed", "social_feed_stale", ["stale > 30m"])

    assert alerts, "Expected escalation alert when feed recovery fails"
    assert alerts[0][1] == "critical"
    assert "social_feed" in alerts[0][0]

    history = layer.get_healing_history(limit=1)[-1]
    assert history.action_type == "social_feed_stale"
    assert history.success is False
