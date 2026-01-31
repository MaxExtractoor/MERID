"""Tests for bot interfaces and self-healing layer."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from importlib.util import module_from_spec, spec_from_file_location
from types import SimpleNamespace

import pytest
import social.telegram_bot_interface as telegram_module

from social.telegram_bot_interface import TelegramBotInterface, TelegramCommand, TelegramMessage
from social.self_healing_social_layer import SelfHealingSocialLayer

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_module(name: str, relative_path: str):
    spec = spec_from_file_location(name, REPO_ROOT / relative_path)
    if not spec or not spec.loader:
        raise RuntimeError(f"Unable to load module {name} from {relative_path}")
    module = module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[attr-defined]
    return module


rag_agent = _load_module("rag_agent_module", "lib/agents/rag_agent.py")
voice_agent = _load_module("voice_agent_module", "lib/agents/voice-agent.py")
relay_module = _load_module("relay_module", "lib/merid/relay.py")


@pytest.mark.asyncio
async def test_telegram_process_command_authorization(monkeypatch):
    bot = TelegramBotInterface(bot_token="test", authorized_users=["user_ok"])

    async def stub_status(cmd: TelegramCommand):
        return TelegramMessage(text="System Status :: stub", chat_id=cmd.chat_id)

    bot._command_handlers["status"] = stub_status

    # Unauthorized user should be rejected
    unauthorized = TelegramCommand(
        command="status",
        args=[],
        user_id="bad_user",
        chat_id="chat",
        timestamp=datetime.utcnow(),
    )
    response = await bot.process_command(unauthorized)
    assert "Unauthorized" in response.text

    # Authorized user should get status message
    authorized = TelegramCommand(
        command="status",
        args=[],
        user_id="user_ok",
        chat_id="chat",
        timestamp=datetime.utcnow(),
    )
    response = await bot.process_command(authorized)
    assert "System Status" in response.text


@pytest.mark.asyncio
async def test_telegram_rate_limit(monkeypatch):
    bot = TelegramBotInterface(bot_token="test", authorized_users=["user"])
    bot._rate_limit_max = 1
    bot._rate_limit_window = 120

    async def stub_status(cmd: TelegramCommand):
        return TelegramMessage(text="System Status :: stub", chat_id=cmd.chat_id)

    bot._command_handlers["status"] = stub_status

    cmd = TelegramCommand(
        command="status",
        args=[],
        user_id="user",
        chat_id="chat",
        timestamp=datetime.utcnow(),
    )

    first = await bot.process_command(cmd)
    assert "System Status" in first.text

    second = await bot.process_command(cmd)
    assert "Rate limit" in second.text


@pytest.mark.asyncio
async def test_self_healing_custom_strategy(monkeypatch):
    layer = SelfHealingSocialLayer()

    async def custom_strategy(target: str, issues):
        custom_strategy.called = True
        return True

    custom_strategy.called = False
    layer.register_recovery_strategy("test_failure", custom_strategy)

    # Patch escalation to avoid network calls
    async def fake_escalate(action):
        fake_escalate.called = True

    fake_escalate.called = False
    monkeypatch.setattr(layer, "_escalate_to_human", fake_escalate)

    await layer._initiate_healing("component", "test_failure", ["issue"])

    assert custom_strategy.called is True
    assert fake_escalate.called is False


@pytest.mark.asyncio
async def test_self_healing_no_strategy(monkeypatch):
    layer = SelfHealingSocialLayer()

    async def fake_escalate(action):
        fake_escalate.called = True

    fake_escalate.called = False
    monkeypatch.setattr(layer, "_escalate_to_human", fake_escalate)

    await layer._initiate_healing("component", "unknown_failure", ["issue"])

    assert fake_escalate.called is True
