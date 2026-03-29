"""Async tests for lifecycle-aligned Telegram notifications.

Run with:
  pytest tests/agents/test_telegram_lifecycle.py -v
"""
from __future__ import annotations

import asyncio
import importlib.util
import pathlib
import sys
import time
from types import SimpleNamespace
from typing import List, Tuple

import pytest

# Load telegram_agent directly to avoid heavy agents/__init__ transitive deps
_agent_file = pathlib.Path(__file__).parent.parent.parent / "agents" / "telegram_agent.py"
_spec = importlib.util.spec_from_file_location("agents.telegram_agent", _agent_file)
telegram_agent = importlib.util.module_from_spec(_spec)
sys.modules["agents.telegram_agent"] = telegram_agent
_spec.loader.exec_module(telegram_agent)

LifecycleStage  = telegram_agent.LifecycleStage
LifecycleStatus = telegram_agent.LifecycleStatus
EpisodeEvent    = telegram_agent.EpisodeEvent
TelegramAgent   = telegram_agent.TelegramAgent


class CapturingBot:
    def __init__(self, token: str):
        self.token = token
        self.calls: List[Tuple[str, float]] = []

    async def send_message(self, chat_id: str, text: str, parse_mode: str):
        self.calls.append((text, time.time()))
        return SimpleNamespace(message_id=len(self.calls), text=text, chat_id=chat_id)


def _make_agent(monkeypatch, dedupe_ttl: float = 5.0, min_interval: float = 0.02):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "chat")
    monkeypatch.setenv("TELEGRAM_DEDUPE_TTL", str(dedupe_ttl))
    bot = CapturingBot("tok")
    monkeypatch.setattr(telegram_agent, "Bot", lambda token: bot)
    agent = TelegramAgent()
    agent.min_post_interval = min_interval
    return agent, bot


# ── Enum / dataclass contracts ─────────────────────────────────────────

class TestLifecycleTypes:
    def test_all_stages_present(self):
        assert {s.value for s in LifecycleStage} == {
            "DISCOVER", "ANALYZE", "CONSENSUS", "SIZE",
            "EXECUTE", "MONITOR", "PROMOTE", "PROTECT",
        }

    def test_all_statuses_present(self):
        assert {s.value for s in LifecycleStatus} == {"SUCCESS", "PARTIAL", "FAILURE"}

    def test_episode_event_defaults(self):
        ev = EpisodeEvent(
            episode_id="ep-1",
            stage=LifecycleStage.DISCOVER,
            status=LifecycleStatus.SUCCESS,
        )
        assert ev.assets == []
        assert ev.summary == ""
        assert ev.details == {}
        assert ev.force is False


# ── Message formatting ─────────────────────────────────────────────────

class TestFormatLifecycleText:
    def test_stage_status_in_header(self):
        ev = EpisodeEvent(
            episode_id="abcdef12", stage=LifecycleStage.CONSENSUS,
            status=LifecycleStatus.SUCCESS, assets=["SOL", "XRP"],
        )
        text = TelegramAgent._format_lifecycle_text(ev)
        assert "CONSENSUS" in text
        assert "SUCCESS" in text

    def test_episode_short_id_present(self):
        ev = EpisodeEvent(
            episode_id="abcdef1234567890",
            stage=LifecycleStage.SIZE, status=LifecycleStatus.PARTIAL,
        )
        assert "abcdef12" in TelegramAgent._format_lifecycle_text(ev)

    def test_assets_rendered(self):
        ev = EpisodeEvent(
            episode_id="x1", stage=LifecycleStage.EXECUTE,
            status=LifecycleStatus.SUCCESS, assets=["BTC", "ETH", "SOL"],
        )
        assert "BTC, ETH, SOL" in TelegramAgent._format_lifecycle_text(ev)

    def test_summary_included(self):
        ev = EpisodeEvent(
            episode_id="x2", stage=LifecycleStage.PROTECT,
            status=LifecycleStatus.FAILURE, summary="RTI stale — halted",
        )
        assert "RTI stale" in TelegramAgent._format_lifecycle_text(ev)

    def test_details_rendered(self):
        ev = EpisodeEvent(
            episode_id="x3", stage=LifecycleStage.SIZE,
            status=LifecycleStatus.SUCCESS,
            details={"btc_util": "80%", "sol_util": "40%"},
        )
        text = TelegramAgent._format_lifecycle_text(ev)
        assert "btc_util" in text and "80%" in text


# ── send_lifecycle_event delivery ─────────────────────────────────────

@pytest.mark.asyncio
async def test_lifecycle_event_delivered(monkeypatch):
    agent, bot = _make_agent(monkeypatch)
    await agent.send_lifecycle_event(EpisodeEvent(
        episode_id="ep-001", stage=LifecycleStage.DISCOVER,
        status=LifecycleStatus.SUCCESS, assets=["BTC"],
        summary="BTC breakout detected",
    ))
    await asyncio.sleep(0.15)
    assert len(bot.calls) == 1
    assert "DISCOVER" in bot.calls[0][0]


@pytest.mark.asyncio
async def test_lifecycle_disabled_agent(monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    monkeypatch.setattr(telegram_agent, "Bot", lambda t: CapturingBot(t))
    agent = TelegramAgent()
    result = await agent.send_lifecycle_event(EpisodeEvent(
        episode_id="ep-noop", stage=LifecycleStage.ANALYZE,
        status=LifecycleStatus.SUCCESS,
    ))
    assert result is None


# ── Deduplication ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_duplicate_episode_stage_status_suppressed(monkeypatch):
    agent, bot = _make_agent(monkeypatch, dedupe_ttl=10.0)
    ev = EpisodeEvent(
        episode_id="ep-002", stage=LifecycleStage.CONSENSUS,
        status=LifecycleStatus.SUCCESS, assets=["ETH"],
    )
    await agent.send_lifecycle_event(ev)
    await agent.send_lifecycle_event(ev)  # duplicate
    await asyncio.sleep(0.15)
    assert len(bot.calls) == 1


@pytest.mark.asyncio
async def test_different_status_gets_through(monkeypatch):
    agent, bot = _make_agent(monkeypatch, dedupe_ttl=10.0)
    await agent.send_lifecycle_event(EpisodeEvent(
        episode_id="ep-003", stage=LifecycleStage.EXECUTE,
        status=LifecycleStatus.SUCCESS, assets=["BTC"],
    ))
    await agent.send_lifecycle_event(EpisodeEvent(
        episode_id="ep-003", stage=LifecycleStage.EXECUTE,
        status=LifecycleStatus.FAILURE, assets=["BTC"],
        summary="venue rejected",
    ))
    await asyncio.sleep(0.25)
    assert len(bot.calls) == 2


@pytest.mark.asyncio
async def test_sequential_stages_all_delivered(monkeypatch):
    agent, bot = _make_agent(monkeypatch, dedupe_ttl=10.0)
    for stage in (LifecycleStage.DISCOVER, LifecycleStage.ANALYZE, LifecycleStage.CONSENSUS):
        await agent.send_lifecycle_event(EpisodeEvent(
            episode_id="ep-004", stage=stage,
            status=LifecycleStatus.SUCCESS, assets=["SOL"],
        ))
    await asyncio.sleep(0.3)
    assert len(bot.calls) == 3


# ── PROTECT force bypass ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_protect_failure_bypasses_dedupe(monkeypatch):
    agent, bot = _make_agent(monkeypatch, dedupe_ttl=60.0)
    for _ in range(3):
        await agent.notify_protect(
            episode_id="ep-005", assets=["XRP"],
            summary="RTI stale — halted",
        )
    await asyncio.sleep(0.35)
    assert len(bot.calls) == 3


# ── Convenience wrappers ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_notify_wrappers_emit_correct_stage(monkeypatch):
    agent, bot = _make_agent(monkeypatch, dedupe_ttl=0.01)
    wrappers = [
        (agent.notify_discover,  "DISCOVER"),
        (agent.notify_analyze,   "ANALYZE"),
        (agent.notify_consensus, "CONSENSUS"),
        (agent.notify_size,      "SIZE"),
        (agent.notify_execute,   "EXECUTE"),
        (agent.notify_monitor,   "MONITOR"),
        (agent.notify_promote,   "PROMOTE"),
    ]
    for i, (fn, stage) in enumerate(wrappers):
        await fn(episode_id=f"ep-w{i}", assets=["BTC"], summary=f"test {stage}")
        await asyncio.sleep(0.06)

    await asyncio.sleep(0.2)
    assert len(bot.calls) == len(wrappers)
    for (text, _), (_, expected) in zip(bot.calls, wrappers):
        assert expected in text


@pytest.mark.asyncio
async def test_notify_protect_defaults_failure(monkeypatch):
    agent, bot = _make_agent(monkeypatch)
    await agent.notify_protect(episode_id="ep-p1", assets=["DOGE"], summary="drawdown halt")
    await asyncio.sleep(0.15)
    assert len(bot.calls) == 1
    assert "PROTECT" in bot.calls[0][0]
    assert "FAILURE" in bot.calls[0][0]
