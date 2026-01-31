"""Hermetic integration smoke tests for comms/news agents."""

from __future__ import annotations

import types
from typing import Any

import pytest

from agents.twitter_agent import TwitterAgent
from monitoring.news_agent import NewsSentinel
from notifications.telegram_client import TelegramAlertClient


def test_twitter_agent_disables_when_tweepy_missing(monkeypatch):
    monkeypatch.setattr("agents.twitter_agent.tweepy", None, raising=False)
    agent = TwitterAgent()
    assert agent.enabled is False
    assert agent.client is None


def test_twitter_agent_initializes_with_credentials(monkeypatch):
    class DummyClient:
        def __init__(self, **kwargs: Any):
            self.kwargs = kwargs

    fake_tweepy = types.SimpleNamespace(Client=DummyClient)
    monkeypatch.setattr("agents.twitter_agent.tweepy", fake_tweepy, raising=False)

    creds = {
        "X_BEARER_TOKEN": "test",
        "X_API_KEY": "test",
        "X_API_SECRET": "test",
        "X_ACCESS_TOKEN": "test",
        "X_ACCESS_TOKEN_SECRET": "test",
    }
    for key, value in creds.items():
        monkeypatch.setenv(key, value)

    agent = TwitterAgent()
    assert agent.enabled is True
    assert isinstance(agent.client, DummyClient)


def test_telegram_agent_disabled_without_token(monkeypatch):
    monkeypatch.delenv("MERID_TELEGRAM_BOT_TOKEN", raising=False)
    client = TelegramAlertClient(enabled=True)
    assert client.enabled is False


def test_news_agent_uses_mock_without_live_deps(monkeypatch):
    monkeypatch.setattr(NewsSentinel, "_check_live_feeds_available", lambda self: False)
    sentinel = NewsSentinel(use_live_feeds=True)
    assert sentinel.use_live_feeds is False
    assert sentinel.fetch_headlines(limit=3) == []
