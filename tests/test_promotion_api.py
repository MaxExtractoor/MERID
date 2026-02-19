"""API-level tests for promotion endpoints.

Uses FastAPI TestClient to exercise:
  1. GET /api/operator/promotion-log
  2. POST /api/operator/promotion-override
  3. GET /api/operator/promotion-checklist
  4. GET /api/operator/promotion-report
"""

from __future__ import annotations

import time
from unittest.mock import patch, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from web.api.operator import router as operator_router
from merid.promotion_report import (
    PromotionEvent,
    PromotionLog,
    PromotionReport,
    DomainEligibility,
    AgentPromotion,
    RingResult,
)


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(operator_router)
    return TestClient(app)


@pytest.fixture
def mock_log(tmp_path):
    """A PromotionLog with some pre-populated events."""
    log = PromotionLog(log_file=tmp_path / "api_test_log.json")
    now = time.time()
    log.append(PromotionEvent(now - 100, "domain", "crypto", "unknown", "eligible", source="automation"))
    log.append(PromotionEvent(now - 50, "domain", "equity", "unknown", "blocked", source="automation",
                               reason="ring failed"))
    log.append(PromotionEvent(now - 10, "domain", "crypto", "eligible", "blocked", source="operator",
                               reason="manual demotion by alice"))
    log.append(PromotionEvent(now, "agent", "agent_1", "unknown", "eligible", source="automation"))
    return log


def _make_report() -> PromotionReport:
    r = PromotionReport(timestamp=time.time())
    r.rings = [
        RingResult(name="blueprint", passed=True, checks_passed=5, checks_total=5),
        RingResult(name="paper_matrix", passed=True, checks_passed=40, checks_total=40),
        RingResult(name="agent_gauntlet", passed=False, checks_passed=6, checks_total=8),
    ]
    r.domains = [
        DomainEligibility(domain="crypto", eligible=True, mode="paper"),
        DomainEligibility(domain="equity", eligible=False, mode="paper", blockers=["ring failed"]),
    ]
    r.agents = [
        AgentPromotion(agent_id="agent_1", category="research", promoted=True, slo_pass_rate=1.0),
        AgentPromotion(agent_id="agent_2", category="strategy", promoted=False, slo_pass_rate=0.75,
                       failed_slos=["latency_p95"]),
    ]
    return r


# ═══════════════════════════════════════════════════════════════════════
# 1. GET /api/operator/promotion-log
# ═══════════════════════════════════════════════════════════════════════

class TestPromotionLogEndpoint:

    def test_returns_events(self, client, mock_log):
        with patch("merid.promotion_report.get_promotion_log", return_value=mock_log):
            resp = client.get("/api/operator/promotion-log")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_events"] == 4
        assert data["returned"] == 4
        assert len(data["events"]) == 4

    def test_filter_by_entity_type(self, client, mock_log):
        with patch("merid.promotion_report.get_promotion_log", return_value=mock_log):
            resp = client.get("/api/operator/promotion-log?entity_type=agent")
        data = resp.json()
        assert data["returned"] == 1
        assert data["events"][0]["entity_type"] == "agent"

    def test_filter_by_entity_id(self, client, mock_log):
        with patch("merid.promotion_report.get_promotion_log", return_value=mock_log):
            resp = client.get("/api/operator/promotion-log?entity_id=crypto")
        data = resp.json()
        assert data["returned"] == 2
        assert all(e["entity_id"] == "crypto" for e in data["events"])

    def test_filter_by_source(self, client, mock_log):
        with patch("merid.promotion_report.get_promotion_log", return_value=mock_log):
            resp = client.get("/api/operator/promotion-log?source=operator")
        data = resp.json()
        assert data["returned"] == 1
        assert data["events"][0]["source"] == "operator"

    def test_limit_parameter(self, client, mock_log):
        with patch("merid.promotion_report.get_promotion_log", return_value=mock_log):
            resp = client.get("/api/operator/promotion-log?limit=2")
        data = resp.json()
        assert data["returned"] == 2
        assert data["total_events"] == 4

    def test_events_have_source_field(self, client, mock_log):
        with patch("merid.promotion_report.get_promotion_log", return_value=mock_log):
            resp = client.get("/api/operator/promotion-log")
        data = resp.json()
        for event in data["events"]:
            assert "source" in event
            assert event["source"] in ("automation", "operator", "system")

    def test_empty_log(self, client, tmp_path):
        empty_log = PromotionLog(log_file=tmp_path / "empty.json")
        with patch("merid.promotion_report.get_promotion_log", return_value=empty_log):
            resp = client.get("/api/operator/promotion-log")
        data = resp.json()
        assert data["total_events"] == 0
        assert data["returned"] == 0
        assert data["events"] == []


# ═══════════════════════════════════════════════════════════════════════
# 2. POST /api/operator/promotion-override
# ═══════════════════════════════════════════════════════════════════════

class TestPromotionOverrideEndpoint:

    def test_promote_domain(self, client, tmp_path):
        log = PromotionLog(log_file=tmp_path / "override1.json")
        with patch("merid.promotion_report.get_promotion_log", return_value=log):
            resp = client.post("/api/operator/promotion-override", json={
                "action": "promote",
                "entity_type": "domain",
                "entity_id": "crypto",
                "reason": "passed manual review",
                "operator": "alice",
            })
        assert resp.status_code == 200
        data = resp.json()
        assert data["entity_type"] == "domain"
        assert data["entity_id"] == "crypto"
        assert data["new_status"] == "eligible"
        assert data["source"] == "operator"

    def test_demote_agent(self, client, tmp_path):
        log = PromotionLog(log_file=tmp_path / "override2.json")
        with patch("merid.promotion_report.get_promotion_log", return_value=log):
            resp = client.post("/api/operator/promotion-override", json={
                "action": "demote",
                "entity_type": "agent",
                "entity_id": "agent_1",
                "reason": "SLO regression",
                "operator": "bob",
            })
        assert resp.status_code == 200
        data = resp.json()
        assert data["new_status"] == "blocked"
        assert data["source"] == "operator"

    def test_invalid_action(self, client):
        resp = client.post("/api/operator/promotion-override", json={
            "action": "invalid",
            "entity_type": "domain",
            "entity_id": "crypto",
        })
        assert resp.status_code == 400

    def test_invalid_entity_type(self, client):
        resp = client.post("/api/operator/promotion-override", json={
            "action": "promote",
            "entity_type": "invalid",
            "entity_id": "crypto",
        })
        assert resp.status_code == 400

    def test_missing_entity_id(self, client):
        resp = client.post("/api/operator/promotion-override", json={
            "action": "promote",
            "entity_type": "domain",
        })
        assert resp.status_code == 400

    def test_override_persists_to_log(self, client, tmp_path):
        log = PromotionLog(log_file=tmp_path / "override3.json")
        with patch("merid.promotion_report.get_promotion_log", return_value=log):
            client.post("/api/operator/promotion-override", json={
                "action": "promote",
                "entity_type": "domain",
                "entity_id": "equity",
                "operator": "charlie",
            })
        assert len(log) == 1
        assert log.events()[0].source == "operator"


# ═══════════════════════════════════════════════════════════════════════
# 3. GET /api/operator/promotion-checklist
# ═══════════════════════════════════════════════════════════════════════

class TestPromotionChecklistEndpoint:

    def test_returns_checklist(self, client):
        report = _make_report()
        with patch("merid.promotion_report.get_cached_promotion_report", return_value=report):
            resp = client.get("/api/operator/promotion-checklist")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) > 0
        for step in data:
            assert "name" in step
            assert "status" in step

    def test_domain_filter(self, client):
        report = _make_report()
        with patch("merid.promotion_report.get_cached_promotion_report", return_value=report):
            resp = client.get("/api/operator/promotion-checklist?domain=crypto")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)


# ═══════════════════════════════════════════════════════════════════════
# 4. GET /api/operator/promotion-report
# ═══════════════════════════════════════════════════════════════════════

class TestPromotionReportEndpoint:

    def test_returns_report(self, client):
        report = _make_report()
        with patch("merid.promotion_report.get_cached_promotion_report", return_value=report):
            resp = client.get("/api/operator/promotion-report")
        assert resp.status_code == 200
        data = resp.json()
        assert "overall_eligible" in data
        assert "rings" in data
        assert "domains" in data
        assert "agents" in data

    def test_report_structure(self, client):
        report = _make_report()
        with patch("merid.promotion_report.get_cached_promotion_report", return_value=report):
            resp = client.get("/api/operator/promotion-report")
        data = resp.json()
        assert len(data["rings"]) == 3
        assert len(data["domains"]["detail"]) == 2
        assert len(data["agents"]["detail"]) == 2
        assert "crypto" in data["domains"]["eligible"]
        assert "equity" in data["domains"]["blocked"]
