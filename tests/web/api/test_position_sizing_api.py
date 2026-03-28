"""
Comprehensive tests for Position Sizing API

Tests Kelly utilization metrics, sizing methods, adjustments, and audit trails.
"""

import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient
from datetime import datetime, timedelta


# ── Fixtures ────────────────────────────────────────────────────────────


@pytest.fixture()
def client():
    """Create test client with position sizing router"""
    from fastapi import FastAPI
    from web.api.position_sizing_api import router

    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


@pytest.fixture()
def mock_position_sizer():
    """Mock PositionSizer for testing"""
    sizer = MagicMock()

    # Kelly metrics
    sizer.get_kelly_metrics.return_value = {
        "current_utilization": 0.25,
        "recommended_fraction": 0.25,
        "safety_factor": 0.5,
        "by_domain": {
            "crypto": {"utilization": 0.2, "fraction": 0.2},
            "prediction": {"utilization": 0.3, "fraction": 0.3},
        },
        "historical_avg": 0.25,
        "max_utilization": 0.4,
        "min_utilization": 0.15,
        "last_updated": datetime.utcnow().isoformat(),
    }

    # Adjustment history
    sizer.get_adjustment_history.return_value = [
        {
            "timestamp": datetime.utcnow().isoformat(),
            "symbol": "BTC",
            "domain": "crypto",
            "base_size": 1000.0,
            "adjusted_size": 800.0,
            "factor": 0.8,
            "reason": "cqi_throttle",
            "type": "throttle",
        }
    ]

    # Adjustment summary
    sizer.get_adjustment_summary.return_value = {
        "total_adjustments": 10,
        "throttled": 8,
        "boosted": 1,
        "capped": 1,
        "by_reason": {
            "cqi_throttle": 5,
            "risk_throttle": 2,
            "volatility_throttle": 1,
        },
        "avg_reduction_pct": 15.0,
        "max_reduction_pct": 30.0,
        "time_window_hours": 24,
    }

    # Decision history
    sizer.get_decision_history.return_value = [
        {
            "timestamp": datetime.utcnow().isoformat(),
            "symbol": "BTC",
            "domain": "crypto",
            "venue": "kalshi",
            "method": "kelly",
            "base_size": 1000.0,
            "adjusted_size": 800.0,
            "adjustment_factor": 0.8,
            "adjustments": [
                {"type": "cqi_throttle", "factor": 0.9, "reason": "Low consensus quality"},
                {"type": "risk_cap", "factor": 0.889, "reason": "Exposure limit"},
            ],
            "confidence": 0.7,
            "kelly_fraction": 0.25,
            "volatility_adjustment": 1.0,
            "reason": "Standard Kelly sizing with adjustments",
        }
    ]

    # Volatility metrics
    sizer.get_volatility_metrics.return_value = {
        "by_asset": {
            "BTC": {
                "daily_vol": 0.03,
                "hourly_vol": 0.012,
                "atr": 1200.0,
                "vol_percentile": 0.65,
                "scaling_factor": 1.0,
            },
            "ETH": {
                "daily_vol": 0.035,
                "hourly_vol": 0.014,
                "atr": 80.0,
                "vol_percentile": 0.70,
                "scaling_factor": 0.95,
            },
        },
        "market_vol_regime": "medium",
        "last_updated": datetime.utcnow().isoformat(),
    }

    # Configuration
    sizer.get_config.return_value = {
        "default_method": "kelly",
        "kelly_safety_factor": 0.5,
        "max_position_size_usd": 5000.0,
        "min_position_size_usd": 10.0,
        "volatility_lookback_days": 30,
        "adjustment_enabled": True,
        "domains": {
            "crypto": {"max_size_usd": 5000, "preferred_method": "volatility"},
            "prediction": {"max_size_usd": 1000, "preferred_method": "kelly"},
        },
    }

    return sizer


# ── Kelly Metrics Tests ────────────────────────────────────────────────


def test_get_kelly_metrics(client, mock_position_sizer):
    """Test getting Kelly utilization metrics"""
    with patch("web.api.position_sizing_api.get_position_sizer", return_value=mock_position_sizer):
        response = client.get("/api/v1/position-sizing/kelly-metrics")

        assert response.status_code == 200
        data = response.json()

        assert "current_utilization" in data
        assert "recommended_fraction" in data
        assert "safety_factor" in data
        assert "by_domain" in data
        assert "historical_avg" in data

        assert data["current_utilization"] == 0.25
        assert data["safety_factor"] == 0.5
        assert "crypto" in data["by_domain"]
        assert "prediction" in data["by_domain"]


def test_get_kelly_metrics_fallback(client):
    """Test Kelly metrics fallback when position sizer unavailable"""
    with patch("web.api.position_sizing_api.get_position_sizer", side_effect=ImportError):
        response = client.get("/api/v1/position-sizing/kelly-metrics")

        assert response.status_code == 200
        data = response.json()

        # Should return default metrics
        assert "current_utilization" in data
        assert data["current_utilization"] == 0.25  # Default


def test_get_kelly_metrics_kalshi_fallback(client):
    """Test Kelly metrics fallback to Kalshi-specific sizer"""
    mock_kalshi_sizer = MagicMock()
    mock_kalshi_sizer.get_kelly_metrics.return_value = {
        "current_utilization": 0.3,
        "recommended_fraction": 0.3,
        "safety_factor": 0.5,
        "by_domain": {},
        "historical_avg": 0.3,
        "max_utilization": 0.5,
        "min_utilization": 0.1,
        "last_updated": datetime.utcnow().isoformat(),
    }

    with patch("web.api.position_sizing_api.get_position_sizer", side_effect=ImportError):
        with patch("web.api.position_sizing_api.get_kalshi_position_sizer", return_value=mock_kalshi_sizer):
            response = client.get("/api/v1/position-sizing/kelly-metrics")

            assert response.status_code == 200
            data = response.json()

            assert data["current_utilization"] == 0.3


# ── Sizing Methods Tests ───────────────────────────────────────────────


def test_get_sizing_methods(client):
    """Test getting available sizing methods"""
    response = client.get("/api/v1/position-sizing/methods")

    assert response.status_code == 200
    data = response.json()

    assert "methods" in data
    assert "default_method" in data
    assert "last_updated" in data

    assert len(data["methods"]) >= 4  # Kelly, Volatility, Fixed, Risk Parity

    # Check method structure
    kelly_method = next(m for m in data["methods"] if m["id"] == "kelly")
    assert kelly_method["name"] == "Kelly Criterion"
    assert kelly_method["active"] is True
    assert "description" in kelly_method
    assert "domains" in kelly_method


def test_get_sizing_methods_default(client):
    """Test that default sizing method is Kelly"""
    response = client.get("/api/v1/position-sizing/methods")

    assert response.status_code == 200
    data = response.json()

    assert data["default_method"] == "kelly"


# ── Size Adjustments Tests ─────────────────────────────────────────────


def test_get_recent_adjustments(client, mock_position_sizer):
    """Test getting recent size adjustments"""
    with patch("web.api.position_sizing_api.get_position_sizer", return_value=mock_position_sizer):
        response = client.get("/api/v1/position-sizing/adjustments/recent?limit=50")

        assert response.status_code == 200
        data = response.json()

        assert "adjustments" in data
        assert "total" in data
        assert "throttled_count" in data
        assert "avg_adjustment_factor" in data

        assert len(data["adjustments"]) >= 1
        adjustment = data["adjustments"][0]
        assert "timestamp" in adjustment
        assert "symbol" in adjustment
        assert "base_size" in adjustment
        assert "adjusted_size" in adjustment
        assert "factor" in adjustment
        assert "reason" in adjustment
        assert "type" in adjustment


def test_get_recent_adjustments_with_domain_filter(client, mock_position_sizer):
    """Test getting adjustments filtered by domain"""
    with patch("web.api.position_sizing_api.get_position_sizer", return_value=mock_position_sizer):
        response = client.get("/api/v1/position-sizing/adjustments/recent?domain=crypto")

        assert response.status_code == 200
        data = response.json()

        assert "adjustments" in data
        mock_position_sizer.get_adjustment_history.assert_called_once()


def test_get_adjustments_summary(client, mock_position_sizer):
    """Test getting adjustments summary"""
    with patch("web.api.position_sizing_api.get_position_sizer", return_value=mock_position_sizer):
        response = client.get("/api/v1/position-sizing/adjustments/summary?hours=24")

        assert response.status_code == 200
        data = response.json()

        assert "total_adjustments" in data
        assert "throttled" in data
        assert "boosted" in data
        assert "capped" in data
        assert "by_reason" in data
        assert "avg_reduction_pct" in data
        assert "max_reduction_pct" in data
        assert "time_window_hours" in data

        assert data["total_adjustments"] == 10
        assert data["throttled"] == 8
        assert data["avg_reduction_pct"] == 15.0


def test_get_adjustments_summary_empty(client):
    """Test adjustments summary when no sizer available"""
    with patch("web.api.position_sizing_api.get_position_sizer", side_effect=ImportError):
        response = client.get("/api/v1/position-sizing/adjustments/summary")

        assert response.status_code == 200
        data = response.json()

        # Should return default/empty summary
        assert data["total_adjustments"] == 0
        assert data["throttled"] == 0


# ── Sizing Decision Audit Trail Tests ──────────────────────────────────


def test_get_recent_decisions(client, mock_position_sizer):
    """Test getting recent sizing decisions"""
    with patch("web.api.position_sizing_api.get_position_sizer", return_value=mock_position_sizer):
        response = client.get("/api/v1/position-sizing/decisions/recent?limit=100")

        assert response.status_code == 200
        data = response.json()

        assert "decisions" in data
        assert "total" in data
        assert "avg_size" in data
        assert "avg_adjustment_factor" in data

        assert len(data["decisions"]) >= 1
        decision = data["decisions"][0]

        # Check decision structure
        assert "timestamp" in decision
        assert "symbol" in decision
        assert "domain" in decision
        assert "venue" in decision
        assert "method" in decision
        assert "base_size" in decision
        assert "adjusted_size" in decision
        assert "adjustment_factor" in decision
        assert "adjustments" in decision
        assert "confidence" in decision
        assert "kelly_fraction" in decision
        assert "reason" in decision

        # Check adjustments list
        assert len(decision["adjustments"]) >= 1
        adj = decision["adjustments"][0]
        assert "type" in adj
        assert "factor" in adj
        assert "reason" in adj


def test_get_recent_decisions_with_filters(client, mock_position_sizer):
    """Test getting decisions with domain and method filters"""
    with patch("web.api.position_sizing_api.get_position_sizer", return_value=mock_position_sizer):
        response = client.get("/api/v1/position-sizing/decisions/recent?domain=crypto&method=kelly")

        assert response.status_code == 200
        data = response.json()

        assert "decisions" in data
        mock_position_sizer.get_decision_history.assert_called_once()


def test_get_recent_decisions_empty(client):
    """Test decisions when no sizer available"""
    with patch("web.api.position_sizing_api.get_position_sizer", side_effect=ImportError):
        response = client.get("/api/v1/position-sizing/decisions/recent")

        assert response.status_code == 200
        data = response.json()

        # Should return empty
        assert data["total"] == 0
        assert len(data["decisions"]) == 0


# ── Volatility Metrics Tests ───────────────────────────────────────────


def test_get_volatility_metrics(client, mock_position_sizer):
    """Test getting volatility metrics"""
    with patch("web.api.position_sizing_api.get_position_sizer", return_value=mock_position_sizer):
        response = client.get("/api/v1/position-sizing/volatility")

        assert response.status_code == 200
        data = response.json()

        assert "by_asset" in data
        assert "market_vol_regime" in data
        assert "last_updated" in data

        assert "BTC" in data["by_asset"]
        assert "ETH" in data["by_asset"]

        btc_vol = data["by_asset"]["BTC"]
        assert "daily_vol" in btc_vol
        assert "hourly_vol" in btc_vol
        assert "atr" in btc_vol
        assert "vol_percentile" in btc_vol
        assert "scaling_factor" in btc_vol

        assert data["market_vol_regime"] == "medium"


def test_get_volatility_metrics_kalshi_fallback(client):
    """Test volatility metrics fallback to Kalshi sizer"""
    mock_kalshi_sizer = MagicMock()
    mock_kalshi_sizer.get_volatility_metrics.return_value = {
        "by_asset": {"BTC": {"daily_vol": 0.03}},
        "market_vol_regime": "high",
        "last_updated": datetime.utcnow().isoformat(),
    }

    with patch("web.api.position_sizing_api.get_position_sizer", side_effect=ImportError):
        with patch("web.api.position_sizing_api.get_kalshi_position_sizer", return_value=mock_kalshi_sizer):
            response = client.get("/api/v1/position-sizing/volatility")

            assert response.status_code == 200
            data = response.json()

            assert data["market_vol_regime"] == "high"


def test_get_volatility_metrics_empty(client):
    """Test volatility metrics when no sizer available"""
    with patch("web.api.position_sizing_api.get_position_sizer", side_effect=ImportError):
        with patch("web.api.position_sizing_api.get_kalshi_position_sizer", side_effect=ImportError):
            response = client.get("/api/v1/position-sizing/volatility")

            assert response.status_code == 200
            data = response.json()

            # Should return default
            assert "by_asset" in data
            assert data["market_vol_regime"] == "medium"


# ── Configuration Tests ────────────────────────────────────────────────


def test_get_sizing_config(client, mock_position_sizer):
    """Test getting sizing configuration"""
    with patch("web.api.position_sizing_api.get_position_sizer", return_value=mock_position_sizer):
        response = client.get("/api/v1/position-sizing/config")

        assert response.status_code == 200
        data = response.json()

        assert "default_method" in data
        assert "kelly_safety_factor" in data
        assert "max_position_size_usd" in data
        assert "min_position_size_usd" in data
        assert "volatility_lookback_days" in data
        assert "adjustment_enabled" in data
        assert "domains" in data

        assert data["default_method"] == "kelly"
        assert data["kelly_safety_factor"] == 0.5
        assert data["max_position_size_usd"] == 5000.0

        # Check domain configs
        assert "crypto" in data["domains"]
        assert "prediction" in data["domains"]


def test_get_sizing_config_default(client):
    """Test config fallback when sizer unavailable"""
    with patch("web.api.position_sizing_api.get_position_sizer", side_effect=ImportError):
        response = client.get("/api/v1/position-sizing/config")

        assert response.status_code == 200
        data = response.json()

        # Should return default config
        assert data["default_method"] == "kelly"
        assert data["kelly_safety_factor"] == 0.5


# ── Health Check Tests ─────────────────────────────────────────────────


def test_sizing_health_check(client, mock_position_sizer):
    """Test position sizing health check"""
    with patch("web.api.position_sizing_api.get_position_sizer", return_value=mock_position_sizer):
        response = client.get("/api/v1/position-sizing/health")

        assert response.status_code == 200
        data = response.json()

        assert "status" in data
        assert "components" in data
        assert "healthy_components" in data
        assert "total_components" in data

        assert data["status"] == "healthy"
        assert data["components"]["position_sizer"] is True
        assert data["components"]["kelly_calculator"] is True
        assert data["components"]["adjustment_engine"] is True


def test_sizing_health_check_degraded(client):
    """Test health check when sizer unavailable"""
    with patch("web.api.position_sizing_api.get_position_sizer", side_effect=ImportError):
        response = client.get("/api/v1/position-sizing/health")

        assert response.status_code == 200
        data = response.json()

        assert data["status"] == "degraded"
        assert data["components"]["position_sizer"] is False


# ── Edge Cases ─────────────────────────────────────────────────────────


def test_get_adjustments_large_limit(client, mock_position_sizer):
    """Test requesting large number of adjustments"""
    with patch("web.api.position_sizing_api.get_position_sizer", return_value=mock_position_sizer):
        response = client.get("/api/v1/position-sizing/adjustments/recent?limit=1000")

        assert response.status_code == 200
        data = response.json()

        # Should handle large limits gracefully
        assert "adjustments" in data


def test_get_decisions_zero_limit(client, mock_position_sizer):
    """Test requesting decisions with zero limit"""
    with patch("web.api.position_sizing_api.get_position_sizer", return_value=mock_position_sizer):
        response = client.get("/api/v1/position-sizing/decisions/recent?limit=0")

        # Should still work, just return empty
        assert response.status_code == 200


def test_get_adjustments_summary_custom_hours(client, mock_position_sizer):
    """Test adjustments summary with custom time window"""
    with patch("web.api.position_sizing_api.get_position_sizer", return_value=mock_position_sizer):
        response = client.get("/api/v1/position-sizing/adjustments/summary?hours=72")

        assert response.status_code == 200
        data = response.json()

        assert data["time_window_hours"] == 72
