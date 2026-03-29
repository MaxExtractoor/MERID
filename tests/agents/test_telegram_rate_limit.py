import asyncio
import sys
import time
from types import SimpleNamespace

import pytest
from telegram.error import TelegramError

# Stub heavy optional dependencies before importing the agent package
sys.modules.setdefault("neo4j", SimpleNamespace(GraphDatabase=None))
sys.modules.setdefault("db.neo4j", SimpleNamespace(memory=None, GraphDatabase=None))

from agents import telegram_agent


class DummyBot:
    """Minimal async Bot stub that records send attempts."""

    def __init__(self, token: str):
        self.token = token
        self.calls = []

    async def send_message(self, chat_id: str, text: str, parse_mode: str):
        ts = time.time()
        self.calls.append((text, ts))
        return SimpleNamespace(message_id=len(self.calls), text=text, chat_id=chat_id)


class RetryOnceBot(DummyBot):
    """Bot stub that raises a retryable error once before succeeding."""

    def __init__(self, token: str, retry_after: float = 0.1):
        super().__init__(token)
        self.retry_after = retry_after
        self._failed_once = False

    async def send_message(self, chat_id: str, text: str, parse_mode: str):
        ts = time.time()
        if not self._failed_once:
            self._failed_once = True
            self.calls.append(("retry", ts))

            class _RetryExc(TelegramError):
                def __init__(self, retry_after: float):
                    super().__init__("Too Many Requests")
                    self.retry_after = retry_after

            raise _RetryExc(self.retry_after)

        self.calls.append((text, ts))
        return SimpleNamespace(message_id=len(self.calls), text=text, chat_id=chat_id)


@pytest.mark.asyncio
async def test_telegram_dedupe_and_rate_limit(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "chat")
    monkeypatch.setenv("TELEGRAM_QUEUE_MAXSIZE", "5")
    monkeypatch.setenv("TELEGRAM_DEDUPE_TTL", "2")

    bot = DummyBot("token")
    monkeypatch.setattr(telegram_agent, "Bot", lambda token: bot)

    agent = telegram_agent.TelegramAgent()
    agent.min_post_interval = 0.05  # speed up tests

    await agent.send_message("hello")
    # Duplicate should be dropped
    await agent.send_message("hello")
    # Unique message should enqueue
    await agent.send_message("world")

    await asyncio.sleep(0.2)  # allow background worker to flush

    assert [c[0] for c in bot.calls] == ["hello", "world"]
    # Second send should respect rate-limit spacing
    assert bot.calls[1][1] - bot.calls[0][1] >= 0.04


@pytest.mark.asyncio
async def test_telegram_retry_after(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "chat")

    bot = RetryOnceBot("token", retry_after=0.05)
    monkeypatch.setattr(telegram_agent, "Bot", lambda token: bot)

    agent = telegram_agent.TelegramAgent()
    agent.min_post_interval = 0.01
    start = time.time()

    await agent.send_message("ok")
    await asyncio.sleep(0.2)

    # One failed attempt, one success
    assert len(bot.calls) == 2
    assert bot.calls[-1][0] == "ok"
    # Backoff respected
    assert bot.calls[-1][1] - start >= 0.05
