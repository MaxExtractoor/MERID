"""Tests for social.x_bot_interface safety behavior."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from types import SimpleNamespace

from social.x_bot_interface import XBotService, XBotUserProfile, XBotRole
from social.x_bot_commands import CommandDefinition
from social.social_aware_quant import BotCommandType


class DummyBackend:
    def __init__(self):
        self.calls = []

    async def request(self, method, endpoint, params=None, json_body=None):
        self.calls.append((method, endpoint, params, json_body))
        return {"system_running": True, "incidents": 0}, 200

    async def close(self):
        return None


class PermissiveBreachSystem:
    def __init__(self) -> None:
        self.auth_failures = []
        self.permissions = []
        self.anomalies = []

    def detect_auth_failure(self, *args, **kwargs):
        self.auth_failures.append((args, kwargs))

    def check_permission(self, **kwargs) -> bool:
        self.permissions.append(kwargs)
        return True

    def detect_anomalous_order(self, **kwargs):
        event = SimpleNamespace(category=None, threat_level=None, evidence={})
        event.evidence.update(kwargs)
        self.anomalies.append(event)
        return event


@pytest.fixture(autouse=True)
def patch_breach_detection(monkeypatch):
    system = PermissiveBreachSystem()
    monkeypatch.setattr(
        "social.x_bot_interface.get_breach_detection_system",
        lambda: system,
    )
    return system


@pytest.mark.asyncio
async def test_per_user_rate_limit_blocks_repeated_commands(monkeypatch):
    backend = DummyBackend()
    service = XBotService(backend_client=backend)
    await service.start()

    profile = XBotUserProfile(user_id="u1", handle="user1", max_commands_per_hour=1)
    service.register_user(profile)

    def fake_get_profile(user_id, handle):  # pragma: no cover - deterministic
        return profile

    monkeypatch.setattr(service._auth, "get_profile", fake_get_profile)

    mention = {"user_id": "u1", "text": "!status", "handle": "user1"}
    await service.process_mention(mention)
    result = await service.process_mention(mention)

    assert result is None
    assert len(backend.calls) == 1


@pytest.mark.asyncio
async def test_auth_gating_blocks_sensitive_command(monkeypatch):
    backend = DummyBackend()
    commands = {
        "incidents": CommandDefinition(
            name="incidents",
            endpoint="/x/incidents",
            method="GET",
            required_role=XBotRole.ADMIN,
            command_type=BotCommandType.READ_ONLY,
            description="Incident summaries",
            risk_level="high",
        )
    }
    service = XBotService(command_definitions=commands, backend_client=backend)
    await service.start()

    user = XBotUserProfile(user_id="u2", handle="user2", role=XBotRole.USER)
    service.register_user(user)

    def fake_get_profile(*_):
        return user

    monkeypatch.setattr(service._auth, "get_profile", fake_get_profile)

    mention = {"user_id": "u2", "text": "!incidents", "handle": "user2", "ip": "1.2.3.4"}
    result = await service.process_mention(mention)

    assert result is None
    assert backend.calls == []


@pytest.mark.asyncio
async def test_incident_command_routes_to_breach_detection(monkeypatch):
    triggered = []

    async def fake_callback(payload):
        triggered.append(payload)

    backend = DummyBackend()
    service = XBotService(backend_client=backend, incident_callback=fake_callback)
    await service.start()

    profile = XBotUserProfile(user_id="u3", handle="ops", role=XBotRole.OPS)
    service.register_user(profile)

    def fake_get_profile(*_):
        return profile

    monkeypatch.setattr(service._auth, "get_profile", fake_get_profile)

    mention = {
        "user_id": "u3",
        "handle": "ops",
        "text": "service down !status",
        "id": "msg1",
    }
    await service.process_mention(mention)

    assert triggered, "Incident callback should receive incident intel"
    assert backend.calls  # status command executed once
