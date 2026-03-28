"""
Comprehensive tests for Risk Control Panel API

Tests emergency controls, kill switches, circuit breakers, and protection layers.
"""

import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from fastapi.testclient import TestClient
from datetime import datetime


# ── Fixtures ────────────────────────────────────────────────────────────


@pytest.fixture()
def client():
    """Create test client with risk control panel router"""
    from fastapi import FastAPI
    from web.api.risk_control_panel_api import router

    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


@pytest.fixture()
def mock_execution_guard():
    """Mock ExecutionGuard for testing"""
    guard = MagicMock()

    # Kill switch status
    guard.get_kill_switch_status.return_value = {
        "active": False,
        "reason": None,
        "triggered_at": None,
        "triggered_by": None,
    }

    guard.get_domain_kill_switch_status.return_value = {
        "active": False,
        "reason": None,
    }

    # Circuit breakers
    guard.get_circuit_breaker_status.return_value = []

    # Protection layers
    guard.get_cqi_throttle_status.return_value = {
        "throttling": False,
        "cqi_score": 0.85,
    }

    guard.get_domain_caps_status.return_value = {
        "crypto": {"breached": False, "usage": 0.5},
        "prediction": {"breached": False, "usage": 0.3},
    }

    guard.get_cooldown_status.return_value = {
        "in_cooldown": False,
        "seconds_remaining": 0,
    }

    return guard


@pytest.fixture()
def mock_risk_coordinator():
    """Mock RiskCoordinator for testing"""
    coord = MagicMock()

    coord.halt_manager.is_halted = False
    coord.halt_manager.halt_reason = None

    coord.halt_manager.get_status.return_value = {
        "is_halted": False,
        "halt_reason": None,
        "halted_at": None,
    }

    coord.halt_manager.halt.return_value = True
    coord.halt_manager.resume.return_value = True

    coord.can_trade.return_value = True

    coord.get_comprehensive_risk_status.return_value = {
        "portfolio_risk": {},
        "active_stops": {},
        "monitoring_active": True,
    }

    return coord


# ── Kill Switch Status Tests ───────────────────────────────────────────


def test_get_kill_switch_status_all_inactive(client, mock_execution_guard):
    """Test getting kill switch status when all switches are inactive"""
    with patch("web.api.risk_control_panel_api.get_execution_guard", return_value=mock_execution_guard):
        response = client.get("/api/v1/risk-control/kill-switches/status")

        assert response.status_code == 200
        data = response.json()

        assert "global" in data
        assert "domains" in data
        assert "can_trade" in data
        assert "affected_domains" in data

        assert data["global"]["active"] is False
        assert data["can_trade"] is True
        assert len(data["affected_domains"]) == 0


def test_get_kill_switch_status_global_active(client, mock_execution_guard):
    """Test getting kill switch status when global switch is active"""
    mock_execution_guard.get_kill_switch_status.return_value = {
        "active": True,
        "reason": "emergency_stop",
        "triggered_at": datetime.utcnow().isoformat(),
        "triggered_by": "operator",
    }

    with patch("web.api.risk_control_panel_api.get_execution_guard", return_value=mock_execution_guard):
        response = client.get("/api/v1/risk-control/kill-switches/status")

        assert response.status_code == 200
        data = response.json()

        assert data["global"]["active"] is True
        assert data["global"]["reason"] == "emergency_stop"
        assert data["can_trade"] is False
        assert "crypto" in data["affected_domains"]
        assert "prediction" in data["affected_domains"]
        assert "betting" in data["affected_domains"]


def test_get_kill_switch_status_domain_active(client, mock_execution_guard):
    """Test getting kill switch status when a domain switch is active"""
    def get_domain_status(domain):
        if domain == "crypto":
            return {"active": True, "reason": "high_volatility"}
        return {"active": False, "reason": None}

    mock_execution_guard.get_domain_kill_switch_status.side_effect = get_domain_status

    with patch("web.api.risk_control_panel_api.get_execution_guard", return_value=mock_execution_guard):
        response = client.get("/api/v1/risk-control/kill-switches/status")

        assert response.status_code == 200
        data = response.json()

        assert data["global"]["active"] is False
        assert data["domains"]["crypto"]["active"] is True
        assert data["domains"]["crypto"]["reason"] == "high_volatility"
        assert "crypto" in data["affected_domains"]
        assert data["can_trade"] is False


def test_get_kill_switch_status_fallback_to_coordinator(client, mock_risk_coordinator):
    """Test fallback to risk coordinator when execution guard not available"""
    with patch("web.api.risk_control_panel_api.get_execution_guard", side_effect=ImportError):
        with patch("web.api.risk_control_panel_api.get_risk_coordinator", return_value=mock_risk_coordinator):
            response = client.get("/api/v1/risk-control/kill-switches/status")

            assert response.status_code == 200
            data = response.json()

            assert "global" in data
            assert data["global"]["active"] is False


# ── Kill Switch Activation Tests ───────────────────────────────────────


def test_activate_global_kill_switch(client, mock_execution_guard):
    """Test activating global kill switch"""
    mock_execution_guard.activate_global_kill_switch.return_value = True

    with patch("web.api.risk_control_panel_api.get_execution_guard", return_value=mock_execution_guard):
        response = client.post(
            "/api/v1/risk-control/kill-switches/activate",
            json={
                "domain": None,
                "reason": "testing_emergency_stop",
                "operator": "test_operator",
            }
        )

        assert response.status_code == 200
        data = response.json()

        assert data["success"] is True
        assert data["domain"] == "global"
        assert data["active"] is True
        assert data["reason"] == "testing_emergency_stop"
        assert data["operator"] == "test_operator"

        mock_execution_guard.activate_global_kill_switch.assert_called_once()


def test_activate_domain_kill_switch(client, mock_execution_guard):
    """Test activating domain-specific kill switch"""
    mock_execution_guard.activate_domain_kill_switch.return_value = True

    with patch("web.api.risk_control_panel_api.get_execution_guard", return_value=mock_execution_guard):
        response = client.post(
            "/api/v1/risk-control/kill-switches/activate",
            json={
                "domain": "crypto",
                "reason": "high_volatility",
                "operator": "risk_manager",
            }
        )

        assert response.status_code == 200
        data = response.json()

        assert data["success"] is True
        assert data["domain"] == "crypto"
        assert data["active"] is True

        mock_execution_guard.activate_domain_kill_switch.assert_called_once_with(
            "crypto", "high_volatility", "risk_manager"
        )


def test_deactivate_global_kill_switch(client, mock_execution_guard):
    """Test deactivating global kill switch"""
    mock_execution_guard.deactivate_global_kill_switch.return_value = True

    with patch("web.api.risk_control_panel_api.get_execution_guard", return_value=mock_execution_guard):
        response = client.post(
            "/api/v1/risk-control/kill-switches/deactivate",
            json={
                "domain": None,
                "operator": "test_operator",
            }
        )

        assert response.status_code == 200
        data = response.json()

        assert data["success"] is True
        assert data["domain"] == "global"
        assert data["active"] is False


# ── Circuit Breaker Tests ──────────────────────────────────────────────


def test_get_circuit_breaker_status_empty(client, mock_execution_guard):
    """Test getting circuit breaker status when no breakers exist"""
    with patch("web.api.risk_control_panel_api.get_execution_guard", return_value=mock_execution_guard):
        response = client.get("/api/v1/risk-control/circuit-breakers/status")

        assert response.status_code == 200
        data = response.json()

        assert "breakers" in data
        assert "total_breakers" in data
        assert "open_breakers" in data

        assert data["total_breakers"] == 0
        assert data["open_breakers"] == 0


def test_get_circuit_breaker_status_with_breakers(client, mock_execution_guard):
    """Test getting circuit breaker status with active breakers"""
    mock_execution_guard.get_circuit_breaker_status.return_value = [
        {
            "id": "venue_api_breaker",
            "name": "Venue API Circuit Breaker",
            "state": "OPEN",
            "failure_count": 5,
            "threshold": 3,
            "last_failure": datetime.utcnow().isoformat(),
            "opened_at": datetime.utcnow().isoformat(),
            "recovery_timeout": 60,
            "can_reset": True,
        },
        {
            "id": "data_feed_breaker",
            "name": "Data Feed Circuit Breaker",
            "state": "CLOSED",
            "failure_count": 0,
            "threshold": 5,
            "last_failure": None,
            "opened_at": None,
            "recovery_timeout": 30,
            "can_reset": False,
        }
    ]

    with patch("web.api.risk_control_panel_api.get_execution_guard", return_value=mock_execution_guard):
        response = client.get("/api/v1/risk-control/circuit-breakers/status")

        assert response.status_code == 200
        data = response.json()

        assert data["total_breakers"] == 2
        assert data["open_breakers"] == 1
        assert len(data["breakers"]) == 2

        open_breaker = next(b for b in data["breakers"] if b["state"] == "OPEN")
        assert open_breaker["id"] == "venue_api_breaker"
        assert open_breaker["failure_count"] == 5


def test_reset_circuit_breaker(client, mock_execution_guard):
    """Test resetting a circuit breaker"""
    mock_execution_guard.reset_circuit_breaker.return_value = True

    with patch("web.api.risk_control_panel_api.get_execution_guard", return_value=mock_execution_guard):
        response = client.post(
            "/api/v1/risk-control/circuit-breakers/reset",
            json={
                "circuit_id": "venue_api_breaker",
                "operator": "test_operator",
            }
        )

        assert response.status_code == 200
        data = response.json()

        assert data["success"] is True
        assert data["circuit_id"] == "venue_api_breaker"
        assert data["state"] == "CLOSED"

        mock_execution_guard.reset_circuit_breaker.assert_called_once_with(
            "venue_api_breaker", "test_operator"
        )


# ── Protection Layers Tests ────────────────────────────────────────────


def test_get_protection_layers_status(client, mock_execution_guard):
    """Test getting status of all protection layers"""
    with patch("web.api.risk_control_panel_api.get_execution_guard", return_value=mock_execution_guard):
        with patch("web.api.risk_control_panel_api.get_kill_switch_status") as mock_ks:
            mock_ks.return_value = {
                "global": {"active": False, "reason": None, "triggered_at": None},
                "domains": {
                    "crypto": {"active": False, "reason": None},
                    "prediction": {"active": False, "reason": None},
                },
                "can_trade": True,
                "affected_domains": [],
            }

            response = client.get("/api/v1/risk-control/protection-layers")

            assert response.status_code == 200
            data = response.json()

            assert "layers" in data
            assert "total_blocking" in data
            assert "can_trade" in data

            # Should have 7 protection layers
            assert len(data["layers"]) == 7

            # Check layer structure
            layer = data["layers"][0]
            assert "name" in layer
            assert "layer_number" in layer
            assert "active" in layer
            assert "status" in layer
            assert "description" in layer
            assert "blocking_trades" in layer
            assert "metrics" in layer

            # When no layers are blocking, can_trade should be True
            assert data["can_trade"] is True
            assert data["total_blocking"] == 0


def test_get_protection_layers_with_blocking(client, mock_execution_guard):
    """Test getting protection layers when some are blocking"""
    with patch("web.api.risk_control_panel_api.get_execution_guard", return_value=mock_execution_guard):
        with patch("web.api.risk_control_panel_api.get_kill_switch_status") as mock_ks:
            mock_ks.return_value = {
                "global": {"active": True, "reason": "emergency", "triggered_at": datetime.utcnow().isoformat()},
                "domains": {
                    "crypto": {"active": False, "reason": None},
                    "prediction": {"active": False, "reason": None},
                },
                "can_trade": False,
                "affected_domains": ["crypto", "prediction", "betting"],
            }

            response = client.get("/api/v1/risk-control/protection-layers")

            assert response.status_code == 200
            data = response.json()

            # Global kill switch should be blocking
            assert data["total_blocking"] >= 1
            assert data["can_trade"] is False

            # Find global kill switch layer
            global_ks_layer = next(l for l in data["layers"] if l["layer_number"] == 1)
            assert global_ks_layer["blocking_trades"] is True
            assert global_ks_layer["status"] == "ACTIVE"


# ── Emergency Stop Tests ───────────────────────────────────────────────


def test_emergency_stop_all(client, mock_execution_guard, mock_risk_coordinator):
    """Test emergency stop-all button"""
    mock_execution_guard.activate_global_kill_switch.return_value = True

    with patch("web.api.risk_control_panel_api.get_execution_guard", return_value=mock_execution_guard):
        with patch("web.api.risk_control_panel_api.get_risk_coordinator", return_value=mock_risk_coordinator):
            response = client.post(
                "/api/v1/risk-control/emergency/stop-all",
                json={
                    "reason": "critical_system_error",
                    "operator": "emergency_operator",
                }
            )

            assert response.status_code == 200
            data = response.json()

            assert data["success"] is True
            assert data["status"] == "ALL_TRADING_STOPPED"
            assert "EMERGENCY_STOP" in data["reason"]
            assert data["operator"] == "emergency_operator"

            # Should activate both kill switch and halt manager
            mock_execution_guard.activate_global_kill_switch.assert_called_once()
            mock_risk_coordinator.halt_manager.halt.assert_called_once()


# ── Health Check Tests ─────────────────────────────────────────────────


def test_risk_control_health_check(client, mock_execution_guard, mock_risk_coordinator):
    """Test risk control system health check"""
    with patch("web.api.risk_control_panel_api.get_execution_guard", return_value=mock_execution_guard):
        with patch("web.api.risk_control_panel_api.get_risk_coordinator", return_value=mock_risk_coordinator):
            with patch("web.api.risk_control_panel_api.get_circuit_breaker_status") as mock_cb:
                mock_cb.return_value = {"breakers": [], "total_breakers": 0, "open_breakers": 0}

                with patch("web.api.risk_control_panel_api.get_kill_switch_status") as mock_ks:
                    mock_ks.return_value = {"global": {"active": False}, "domains": {}, "can_trade": True, "affected_domains": []}

                    with patch("web.api.risk_control_panel_api.get_protection_layers_status") as mock_pl:
                        mock_pl.return_value = {"layers": [], "total_blocking": 0, "can_trade": True}

                        response = client.get("/api/v1/risk-control/health")

                        assert response.status_code == 200
                        data = response.json()

                        assert "status" in data
                        assert "components" in data
                        assert "healthy_components" in data
                        assert "total_components" in data

                        # All components should be healthy
                        assert data["status"] == "healthy"
                        assert data["components"]["execution_guard"] is True
                        assert data["components"]["risk_coordinator"] is True


def test_risk_control_health_check_degraded(client):
    """Test health check when some components are unavailable"""
    with patch("web.api.risk_control_panel_api.get_execution_guard", side_effect=ImportError):
        with patch("web.api.risk_control_panel_api.get_risk_coordinator", side_effect=ImportError):
            response = client.get("/api/v1/risk-control/health")

            assert response.status_code == 200
            data = response.json()

            assert data["status"] == "degraded"
            assert data["components"]["execution_guard"] is False
            assert data["components"]["risk_coordinator"] is False


# ── Limit Override Tests ───────────────────────────────────────────────


def test_override_limit(client):
    """Test overriding a risk limit"""
    with patch("web.api.risk_control_panel_api.get_risk_guard") as mock_get_guard:
        mock_guard = MagicMock()
        mock_guard.override_limit.return_value = {
            "old_value": 1000.0,
            "expires_at": datetime.utcnow().isoformat(),
        }
        mock_get_guard.return_value = mock_guard

        response = client.post(
            "/api/v1/risk-control/limits/override",
            json={
                "limit_type": "daily_loss",
                "new_value": 2000.0,
                "duration_seconds": 3600,
                "operator": "test_operator",
                "reason": "temporary_increase",
            }
        )

        assert response.status_code == 200
        data = response.json()

        assert data["success"] is True
        assert data["limit_type"] == "daily_loss"
        assert data["old_value"] == 1000.0
        assert data["new_value"] == 2000.0
        assert data["operator"] == "test_operator"


def test_get_active_overrides(client):
    """Test getting active limit overrides"""
    with patch("web.api.risk_control_panel_api.get_risk_guard") as mock_get_guard:
        mock_guard = MagicMock()
        mock_guard.get_active_overrides.return_value = [
            {
                "limit_type": "daily_loss",
                "old_value": 1000.0,
                "new_value": 2000.0,
                "expires_at": datetime.utcnow().isoformat(),
                "operator": "test_operator",
                "reason": "temporary_increase",
            }
        ]
        mock_get_guard.return_value = mock_guard

        response = client.get("/api/v1/risk-control/limits/overrides")

        assert response.status_code == 200
        data = response.json()

        assert "overrides" in data
        assert "total_overrides" in data
        assert data["total_overrides"] == 1
        assert len(data["overrides"]) == 1
