"""Tests for canonical /api/v1/explainability/decisions endpoint."""

from __future__ import annotations

from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

import web.api.explainability as explainability_api
from web.api.missing_endpoints import router as missing_endpoints_router


class _TrackerStub:
    def __init__(self, decisions):
        self._decisions = list(decisions)

    def get_recent_decisions(self, limit: int):
        return self._decisions[-limit:]

    def get_agent_decisions(self, agent_id: str, limit: int):
        filtered = [d for d in self._decisions if d.agent_id == agent_id]
        return filtered[-limit:]


def _decision(
    *,
    decision_id: str,
    agent_id: str,
    decision: str,
    timestamp: float,
    confidence: float = 0.7,
):
    return SimpleNamespace(
        decision_id=decision_id,
        agent_id=agent_id,
        decision=decision,
        timestamp=timestamp,
        confidence=confidence,
        primary_reason="Edge and liquidity support the action",
        supporting_factors=["positive edge", "tight spread"],
        contrary_factors=["headline volatility"],
        data_sources=["kalshi_orderbook", "news_stream"],
        processing_time_ms=12.5,
    )


def _build_client(monkeypatch, decisions) -> TestClient:
    tracker = _TrackerStub(decisions)
    monkeypatch.setattr(explainability_api, "get_explainability_tracker", lambda: tracker)

    app = FastAPI()
    # Include concrete explainability router first; missing_endpoints remains fallback.
    app.include_router(explainability_api.router)
    app.include_router(missing_endpoints_router)
    return TestClient(app)


def test_dashboard_decisions_returns_normalized_real_data(monkeypatch):
    client = _build_client(
        monkeypatch,
        [
            _decision(
                decision_id="dec-1",
                agent_id="agent-a",
                decision="BUY YES",
                timestamp=1_700_000_000.0,
            )
        ],
    )

    response = client.get("/api/v1/explainability/decisions")
    assert response.status_code == 200

    payload = response.json()
    assert payload.get("_stub") is None
    assert payload["total"] == 1

    record = payload["decisions"][0]
    assert record["id"] == "dec-1"
    assert record["agent_name"] == "agent-a"
    assert record["decision"] == "BUY YES"
    assert record["outcome"] == "pending"
    assert len(record["factors"]) == 3
    assert len(record["data_sources"]) == 2


def test_dashboard_decisions_supports_agent_filter(monkeypatch):
    client = _build_client(
        monkeypatch,
        [
            _decision(
                decision_id="dec-1",
                agent_id="agent-a",
                decision="BUY YES",
                timestamp=1_700_000_000.0,
            ),
            _decision(
                decision_id="dec-2",
                agent_id="agent-b",
                decision="SELL NO",
                timestamp=1_700_000_100.0,
            ),
        ],
    )

    response = client.get("/api/v1/explainability/decisions", params={"agent": "agent-b"})
    assert response.status_code == 200

    payload = response.json()
    assert payload["total"] == 1
    assert payload["decisions"][0]["agent_name"] == "agent-b"
    assert payload["decisions"][0]["id"] == "dec-2"
