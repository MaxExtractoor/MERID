"""
Comprehensive tests for Promotion Status API

Tests 5-ring gauntlet, domain eligibility, agent promotion, and history tracking.
"""

import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient
from datetime import datetime


# ── Fixtures ────────────────────────────────────────────────────────────


@pytest.fixture()
def client():
    """Create test client with promotion status router"""
    from fastapi import FastAPI
    from web.api.promotion_status_api import router

    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


@pytest.fixture()
def mock_promotion_report():
    """Mock PromotionReport for testing"""
    report = MagicMock()

    # All domain status
    report.get_all_domain_status.return_value = {
        "domains": {
            "crypto": {
                "eligible": False,
                "ring": 2,
                "requirements_met": {
                    "pf_gate": True,
                    "expectancy_gate": True,
                    "sharpe_gate": False,
                    "trade_count_gate": False,
                    "stability_gate": False,
                },
                "metrics": {
                    "pf": 1.3,
                    "expectancy": 0.05,
                    "sharpe": 0.3,
                    "trade_count": 50,
                    "stability_score": 0.6,
                },
                "blocking_reason": "Insufficient Sharpe ratio and trade count",
            },
            "prediction": {
                "eligible": True,
                "ring": 5,
                "requirements_met": {
                    "pf_gate": True,
                    "expectancy_gate": True,
                    "sharpe_gate": True,
                    "trade_count_gate": True,
                    "stability_gate": True,
                },
                "metrics": {
                    "pf": 1.5,
                    "expectancy": 0.08,
                    "sharpe": 0.8,
                    "trade_count": 150,
                    "stability_score": 0.85,
                },
                "blocking_reason": None,
            },
        },
        "last_sync": datetime.utcnow().isoformat(),
    }

    # Domain detail
    report.get_domain_detail.return_value = {
        "domain": "prediction",
        "eligible": True,
        "ring": 5,
        "gauntlet": {
            "ring1": {
                "name": "Profitability",
                "passed": True,
                "requirements": {"pf": ">1.2", "expectancy": ">0"},
            },
            "ring2": {
                "name": "Risk-Adjusted Returns",
                "passed": True,
                "requirements": {"sharpe": ">0.5"},
            },
            "ring3": {
                "name": "Statistical Significance",
                "passed": True,
                "requirements": {"trade_count": ">=100"},
            },
            "ring4": {
                "name": "Consistency",
                "passed": True,
                "requirements": {"max_drawdown": "<15%", "stability": ">0.7"},
            },
            "ring5": {
                "name": "Live Readiness",
                "passed": True,
                "requirements": {"all_rings_passed": True, "manual_approval": False},
            },
        },
        "metrics": {
            "pf": 1.5,
            "expectancy": 0.08,
            "sharpe": 0.8,
            "trade_count": 150,
            "win_rate": 0.62,
            "avg_win": 45.0,
            "avg_loss": -30.0,
            "max_drawdown": 8.5,
            "stability_score": 0.85,
        },
        "blocking_reasons": [],
        "next_ring_requirements": {},
        "last_updated": datetime.utcnow().isoformat(),
    }

    # Agent status
    report.get_all_agent_status.return_value = [
        {
            "agent_id": "agent_1",
            "domain": "prediction",
            "promoted": True,
            "blocked": False,
            "performance": {
                "pf": 1.6,
                "sharpe": 0.9,
                "trade_count": 200,
            },
            "blocking_reason": None,
        },
        {
            "agent_id": "agent_2",
            "domain": "crypto",
            "promoted": False,
            "blocked": True,
            "performance": {
                "pf": 0.8,
                "sharpe": -0.2,
                "trade_count": 30,
            },
            "blocking_reason": "Negative Sharpe ratio",
        },
    ]

    # Agent detail
    report.get_agent_detail.return_value = {
        "agent_id": "agent_1",
        "promoted": True,
        "blocked": False,
        "domain": "prediction",
        "performance": {
            "pf": 1.6,
            "sharpe": 0.9,
            "expectancy": 0.1,
            "trade_count": 200,
            "win_rate": 0.65,
        },
        "blocking_reason": None,
        "promotion_history": [
            {
                "timestamp": datetime.utcnow().isoformat(),
                "action": "promoted",
                "operator": "system",
                "reason": "Met all gauntlet requirements",
            }
        ],
    }

    # History
    report.get_history.return_value = [
        {
            "timestamp": datetime.utcnow().isoformat(),
            "domain": "prediction",
            "action": "promoted",
            "reason": "Met all gauntlet requirements",
            "operator": "system",
            "metrics_at_time": {
                "pf": 1.5,
                "sharpe": 0.8,
                "trade_count": 150,
            },
        }
    ]

    return report


@pytest.fixture()
def mock_promotion_engine():
    """Mock PromotionEngine for testing"""
    engine = MagicMock()

    # Domain eligibility
    engine.get_domain_eligibility.return_value = {
        "eligible": True,
        "ring": 5,
        "requirements_met": {
            "pf_gate": True,
            "expectancy_gate": True,
            "sharpe_gate": True,
            "trade_count_gate": True,
            "stability_gate": True,
        },
        "metrics": {
            "pf": 1.5,
            "expectancy": 0.08,
            "sharpe": 0.8,
            "trade_count": 150,
            "stability_score": 0.85,
        },
    }

    # Gauntlet config
    engine.get_gauntlet_config.return_value = {
        "rings": [
            {
                "ring": 1,
                "name": "Profitability",
                "requirements": {
                    "pf": {"threshold": 1.2, "operator": ">"},
                    "expectancy": {"threshold": 0.01, "operator": ">"},
                },
                "description": "Basic profitability: PF > 1.2 and positive expectancy",
            }
        ],
        "auto_promotion_enabled": True,
        "sync_interval_seconds": 300,
    }

    return engine


# ── Promotion Status Tests ─────────────────────────────────────────────


def test_get_promotion_status(client, mock_promotion_report):
    """Test getting overall promotion status"""
    with patch("web.api.promotion_status_api.get_promotion_report", return_value=mock_promotion_report):
        response = client.get("/api/v1/promotion/status")

        assert response.status_code == 200
        data = response.json()

        assert "timestamp" in data
        assert "auto_promotion_enabled" in data
        assert "domains" in data
        assert "eligible_count" in data
        assert "total_domains" in data
        assert "last_sync" in data

        assert data["auto_promotion_enabled"] is True
        assert "crypto" in data["domains"]
        assert "prediction" in data["domains"]

        # Check crypto domain (not eligible)
        crypto = data["domains"]["crypto"]
        assert crypto["eligible"] is False
        assert crypto["ring"] == 2
        assert crypto["blocking_reason"] is not None

        # Check prediction domain (eligible)
        prediction = data["domains"]["prediction"]
        assert prediction["eligible"] is True
        assert prediction["ring"] == 5

        # Eligible count should be 1
        assert data["eligible_count"] == 1


def test_get_promotion_status_fallback(client):
    """Test promotion status fallback when report unavailable"""
    with patch("web.api.promotion_status_api.get_promotion_report", side_effect=ImportError):
        with patch("web.api.promotion_status_api.get_promotion_engine", side_effect=ImportError):
            response = client.get("/api/v1/promotion/status")

            assert response.status_code == 200
            data = response.json()

            # Should return default/placeholder data
            assert data["auto_promotion_enabled"] is False
            assert data["eligible_count"] == 0


# ── Domain Promotion Tests ─────────────────────────────────────────────


def test_get_domain_promotion_status(client, mock_promotion_report):
    """Test getting detailed domain promotion status"""
    with patch("web.api.promotion_status_api.get_promotion_report", return_value=mock_promotion_report):
        response = client.get("/api/v1/promotion/domain/prediction")

        assert response.status_code == 200
        data = response.json()

        assert data["domain"] == "prediction"
        assert data["eligible"] is True
        assert data["ring"] == 5

        # Check gauntlet structure
        assert "gauntlet" in data
        gauntlet = data["gauntlet"]
        assert "ring1" in gauntlet
        assert "ring2" in gauntlet
        assert "ring3" in gauntlet
        assert "ring4" in gauntlet
        assert "ring5" in gauntlet

        # Check ring structure
        ring1 = gauntlet["ring1"]
        assert "name" in ring1
        assert "passed" in ring1
        assert "requirements" in ring1

        # Check metrics
        assert "metrics" in data
        metrics = data["metrics"]
        assert "pf" in metrics
        assert "sharpe" in metrics
        assert "trade_count" in metrics

        # Check blocking reasons
        assert "blocking_reasons" in data
        assert len(data["blocking_reasons"]) == 0  # Eligible domain


def test_get_domain_promotion_status_not_eligible(client, mock_promotion_report):
    """Test getting domain status for non-eligible domain"""
    mock_promotion_report.get_domain_detail.return_value = {
        "domain": "crypto",
        "eligible": False,
        "ring": 2,
        "gauntlet": {},
        "metrics": {
            "pf": 1.3,
            "sharpe": 0.3,
            "trade_count": 50,
        },
        "blocking_reasons": ["Insufficient Sharpe ratio", "Low trade count"],
        "next_ring_requirements": {"sharpe": 0.5, "trade_count": 100},
        "last_updated": datetime.utcnow().isoformat(),
    }

    with patch("web.api.promotion_status_api.get_promotion_report", return_value=mock_promotion_report):
        response = client.get("/api/v1/promotion/domain/crypto")

        assert response.status_code == 200
        data = response.json()

        assert data["eligible"] is False
        assert data["ring"] == 2
        assert len(data["blocking_reasons"]) == 2
        assert "next_ring_requirements" in data


# ── Agent Promotion Tests ──────────────────────────────────────────────


def test_get_agent_promotion_status(client, mock_promotion_report):
    """Test getting agent promotion status"""
    with patch("web.api.promotion_status_api.get_promotion_report", return_value=mock_promotion_report):
        response = client.get("/api/v1/promotion/agents")

        assert response.status_code == 200
        data = response.json()

        assert "agents" in data
        assert "total_agents" in data
        assert "promoted_agents" in data
        assert "blocked_agents" in data

        assert data["total_agents"] == 2
        assert data["promoted_agents"] == 1
        assert data["blocked_agents"] == 1

        # Check agent structure
        agents = data["agents"]
        assert len(agents) == 2

        promoted_agent = next(a for a in agents if a["agent_id"] == "agent_1")
        assert promoted_agent["promoted"] is True
        assert promoted_agent["blocked"] is False
        assert "performance" in promoted_agent

        blocked_agent = next(a for a in agents if a["agent_id"] == "agent_2")
        assert blocked_agent["promoted"] is False
        assert blocked_agent["blocked"] is True
        assert blocked_agent["blocking_reason"] == "Negative Sharpe ratio"


def test_get_agent_promotion_status_from_grid(client):
    """Test getting agent status fallback from agent grid"""
    with patch("web.api.promotion_status_api.get_promotion_report", side_effect=ImportError):
        mock_agent = MagicMock()
        mock_agent.config.agent_id = "test_agent"
        mock_agent.config.domain = "prediction"

        mock_grid = MagicMock()
        mock_grid.agents = [mock_agent]

        with patch("web.api.promotion_status_api.get_agent_grid", return_value=mock_grid):
            response = client.get("/api/v1/promotion/agents")

            assert response.status_code == 200
            data = response.json()

            assert len(data["agents"]) >= 1


def test_get_agent_promotion_detail(client, mock_promotion_report):
    """Test getting detailed agent promotion info"""
    with patch("web.api.promotion_status_api.get_promotion_report", return_value=mock_promotion_report):
        response = client.get("/api/v1/promotion/agents/agent_1")

        assert response.status_code == 200
        data = response.json()

        assert data["agent_id"] == "agent_1"
        assert data["promoted"] is True
        assert data["blocked"] is False
        assert data["domain"] == "prediction"

        # Check performance
        assert "performance" in data
        perf = data["performance"]
        assert "pf" in perf
        assert "sharpe" in perf
        assert "trade_count" in perf

        # Check history
        assert "promotion_history" in data
        assert len(data["promotion_history"]) >= 1


# ── Promotion History Tests ────────────────────────────────────────────


def test_get_promotion_history(client, mock_promotion_report):
    """Test getting promotion history"""
    with patch("web.api.promotion_status_api.get_promotion_report", return_value=mock_promotion_report):
        response = client.get("/api/v1/promotion/history?limit=50")

        assert response.status_code == 200
        data = response.json()

        assert "history" in data
        assert "total" in data

        assert len(data["history"]) >= 1
        event = data["history"][0]

        assert "timestamp" in event
        assert "domain" in event
        assert "action" in event
        assert "reason" in event
        assert "operator" in event
        assert "metrics_at_time" in event


def test_get_promotion_history_with_domain_filter(client, mock_promotion_report):
    """Test getting history filtered by domain"""
    with patch("web.api.promotion_status_api.get_promotion_report", return_value=mock_promotion_report):
        response = client.get("/api/v1/promotion/history?domain=prediction")

        assert response.status_code == 200
        data = response.json()

        assert "history" in data
        mock_promotion_report.get_history.assert_called_once()


def test_get_promotion_history_empty(client):
    """Test history when no report available"""
    with patch("web.api.promotion_status_api.get_promotion_report", side_effect=ImportError):
        response = client.get("/api/v1/promotion/history")

        assert response.status_code == 200
        data = response.json()

        assert data["total"] == 0
        assert len(data["history"]) == 0


# ── Gauntlet Configuration Tests ───────────────────────────────────────


def test_get_gauntlet_config(client, mock_promotion_engine):
    """Test getting gauntlet configuration"""
    with patch("web.api.promotion_status_api.get_promotion_engine", return_value=mock_promotion_engine):
        response = client.get("/api/v1/promotion/gauntlet/config")

        assert response.status_code == 200
        data = response.json()

        assert "rings" in data
        assert "auto_promotion_enabled" in data
        assert "sync_interval_seconds" in data

        assert data["auto_promotion_enabled"] is True
        assert data["sync_interval_seconds"] == 300


def test_get_gauntlet_config_default(client):
    """Test gauntlet config fallback"""
    with patch("web.api.promotion_status_api.get_promotion_engine", side_effect=ImportError):
        response = client.get("/api/v1/promotion/gauntlet/config")

        assert response.status_code == 200
        data = response.json()

        # Should return default config with 5 rings
        assert len(data["rings"]) == 5
        assert data["auto_promotion_enabled"] is True


# ── Manual Override Tests ──────────────────────────────────────────────


def test_override_promotion(client, mock_promotion_engine):
    """Test manual promotion override"""
    mock_promotion_engine.override_eligibility.return_value = {
        "expires_at": datetime.utcnow().isoformat(),
    }

    with patch("web.api.promotion_status_api.get_promotion_engine", return_value=mock_promotion_engine):
        response = client.post(
            "/api/v1/promotion/override",
            json={
                "domain": "crypto",
                "eligible": True,
                "operator": "test_operator",
                "reason": "manual_testing",
                "duration_hours": 24,
            }
        )

        assert response.status_code == 200
        data = response.json()

        assert data["success"] is True
        assert data["domain"] == "crypto"
        assert data["eligible"] is True
        assert data["operator"] == "test_operator"
        assert data["reason"] == "manual_testing"

        mock_promotion_engine.override_eligibility.assert_called_once()


def test_override_promotion_not_implemented(client):
    """Test override when engine not available"""
    with patch("web.api.promotion_status_api.get_promotion_engine", side_effect=ImportError):
        response = client.post(
            "/api/v1/promotion/override",
            json={
                "domain": "crypto",
                "eligible": True,
                "operator": "test_operator",
                "reason": "testing",
            }
        )

        assert response.status_code == 501


def test_get_active_overrides(client, mock_promotion_engine):
    """Test getting active promotion overrides"""
    mock_promotion_engine.get_active_overrides.return_value = [
        {
            "domain": "crypto",
            "eligible": True,
            "expires_at": datetime.utcnow().isoformat(),
            "operator": "test_operator",
            "reason": "manual_testing",
        }
    ]

    with patch("web.api.promotion_status_api.get_promotion_engine", return_value=mock_promotion_engine):
        response = client.get("/api/v1/promotion/overrides")

        assert response.status_code == 200
        data = response.json()

        assert "overrides" in data
        assert "total_overrides" in data
        assert data["total_overrides"] == 1


def test_get_active_overrides_empty(client):
    """Test getting overrides when none exist"""
    with patch("web.api.promotion_status_api.get_promotion_engine", side_effect=ImportError):
        response = client.get("/api/v1/promotion/overrides")

        assert response.status_code == 200
        data = response.json()

        assert data["total_overrides"] == 0


# ── Agent Action Tests ─────────────────────────────────────────────────


def test_agent_promotion_action_promote(client, mock_promotion_report):
    """Test promoting an agent"""
    mock_promotion_report.promote_agent.return_value = True

    with patch("web.api.promotion_status_api.get_promotion_report", return_value=mock_promotion_report):
        response = client.post(
            "/api/v1/promotion/agents/action",
            json={
                "agent_id": "agent_2",
                "action": "promote",
                "operator": "test_operator",
                "reason": "manual_promotion",
            }
        )

        assert response.status_code == 200
        data = response.json()

        assert data["success"] is True
        assert data["agent_id"] == "agent_2"
        assert data["action"] == "promote"

        mock_promotion_report.promote_agent.assert_called_once()


def test_agent_promotion_action_block(client, mock_promotion_report):
    """Test blocking an agent"""
    mock_promotion_report.block_agent.return_value = True

    with patch("web.api.promotion_status_api.get_promotion_report", return_value=mock_promotion_report):
        response = client.post(
            "/api/v1/promotion/agents/action",
            json={
                "agent_id": "agent_1",
                "action": "block",
                "operator": "test_operator",
                "reason": "poor_performance",
            }
        )

        assert response.status_code == 200
        data = response.json()

        assert data["success"] is True
        assert data["action"] == "block"

        mock_promotion_report.block_agent.assert_called_once()


def test_agent_promotion_action_invalid(client, mock_promotion_report):
    """Test invalid agent action"""
    with patch("web.api.promotion_status_api.get_promotion_report", return_value=mock_promotion_report):
        response = client.post(
            "/api/v1/promotion/agents/action",
            json={
                "agent_id": "agent_1",
                "action": "invalid_action",
                "operator": "test_operator",
                "reason": "testing",
            }
        )

        assert response.status_code == 400


# ── Health Check Tests ─────────────────────────────────────────────────


def test_promotion_health_check(client, mock_promotion_report, mock_promotion_engine):
    """Test promotion system health check"""
    with patch("web.api.promotion_status_api.get_promotion_report", return_value=mock_promotion_report):
        with patch("web.api.promotion_status_api.get_promotion_engine", return_value=mock_promotion_engine):
            response = client.get("/api/v1/promotion/health")

            assert response.status_code == 200
            data = response.json()

            assert "status" in data
            assert "components" in data
            assert "healthy_components" in data
            assert "total_components" in data

            assert data["status"] == "healthy"
            assert data["components"]["promotion_report"] is True
            assert data["components"]["promotion_engine"] is True


def test_promotion_health_check_degraded(client):
    """Test health check when components unavailable"""
    with patch("web.api.promotion_status_api.get_promotion_report", side_effect=ImportError):
        with patch("web.api.promotion_status_api.get_promotion_engine", side_effect=ImportError):
            response = client.get("/api/v1/promotion/health")

            assert response.status_code == 200
            data = response.json()

            assert data["status"] == "degraded"
            assert data["components"]["promotion_report"] is False
            assert data["components"]["promotion_engine"] is False
