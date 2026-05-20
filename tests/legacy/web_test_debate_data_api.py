"""
Tests for Debate Data API endpoints (/debates/alerts, /debates/historical-contribution, /debates/rollups)
"""

import pytest
from fastapi.testclient import TestClient
from datetime import datetime, timezone, timedelta
import json

from web.main import create_app
from web.api.auth import get_current_session


class TestDebateDataAPI:
    """Test suite for debate data endpoints."""
    
    @pytest.fixture
    def client(self):
        """Create test client."""
        app = create_app()
        return TestClient(app)
    
    @pytest.fixture
    def mock_session(self, mocker):
        """Mock authentication session."""
        mock = mocker.Mock()
        mock.user_id = "test-user"
        mock.permissions = ["read"]
        return mock
    
    def test_get_debate_alerts_basic(self, client, mocker):
        """Test alerts endpoint with basic parameters."""
        # Mock auth
        mocker.patch("web.api.debate_data_api.get_current_session", return_value=mocker.Mock())
        
        # Mock dependencies
        mock_quota_manager = mocker.Mock()
        mock_quota_manager.get_risk_quota_summary.return_value = {
            "agent-1": {
                "team_id": "team-a",
                "tier": "gold",
                "quota_pct": 0.15,
                "current_risk_pct": 0.12,
                "utilization_pct": 0.8,
                "debate_count": 10,
                "avg_debate_lift": 0.02
            },
            "agent-2": {
                "team_id": "team-b",
                "tier": "silver",
                "quota_pct": 0.08,
                "current_risk_pct": 0.07,
                "utilization_pct": 0.875,
                "debate_count": 5,
                "avg_debate_lift": 0.01
            }
        }
        
        mock_attribution_engine = mocker.AsyncMock()
        mock_attribution_engine.generate_attribution_summary.return_value = mocker.Mock(
            agent_contributions={
                "agent-1": {"debate_contribution_pct": 0.03},
                "agent-2": {"debate_contribution_pct": -0.02}
            }
        )
        
        mocker.patch("merid.prediction.agent_risk_quotas.get_agent_risk_quota_manager", return_value=mock_quota_manager)
        mocker.patch("merid.prediction.pnl_attribution.get_pnl_attribution_engine", return_value=mock_attribution_engine)
        
        response = client.get("/debates/alerts?days_back=7&tier=all&utilization_band=all&problems_only=false")
        
        if response.status_code != 200:
            print(f"Error response: {response.status_code}")
            print(f"Response body: {response.text}")
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["window_days"] == 7
        assert "generated_at" in data
        assert "alerts" in data
        assert len(data["alerts"]) >= 1  # Should have at least 1 alert (agent-2 has negative contribution)
        
        # Check alert structure
        alert = data["alerts"][0]
        assert "agent_id" in alert
        assert "tier" in alert
        assert "utilization_pct" in alert
        assert "metric_id" in alert
        assert "metric_label" in alert
        assert "severity" in alert
        assert "message" in alert
        assert "triggered_at" in alert
        assert "supporting_values" in alert
        
        # Verify severity mapping
        assert alert["severity"] in ["warning", "critical"]
    
    def test_get_debate_alerts_filters(self, client, mocker):
        """Test alerts endpoint with tier and utilization filters."""
        mocker.patch("web.api.debate_data_api.get_current_session", return_value=mocker.Mock())
        
        mock_quota_manager = mocker.Mock()
        mock_quota_manager.get_risk_quota_summary.return_value = {
            "agent-1": {"tier": "gold", "utilization_pct": 0.8},
            "agent-2": {"tier": "silver", "utilization_pct": 0.4}
        }
        
        mock_attribution_engine = mocker.AsyncMock()
        mock_attribution_engine.generate_attribution_summary.return_value = mocker.Mock(
            agent_contributions={"agent-1": {"debate_contribution_pct": 0.01}}
        )
        
        mocker.patch("merid.prediction.agent_risk_quotas.get_agent_risk_quota_manager", return_value=mock_quota_manager)
        mocker.patch("merid.prediction.pnl_attribution.get_pnl_attribution_engine", return_value=mock_attribution_engine)
        
        # Test tier filter
        response = client.get("/debates/alerts?tier=gold")
        assert response.status_code == 200
        data = response.json()
        
        # All alerts should be for gold tier agents
        for alert in data["alerts"]:
            assert alert["tier"] == "gold"
        
        # Test utilization band filter
        response = client.get("/debates/alerts?utilization_band=medium")
        assert response.status_code == 200
        data = response.json()
        
        # Should only include agents with medium utilization (0.33-0.67)
        # agent-1 with 0.8 should be excluded, agent-2 with 0.4 should be included
        for alert in data["alerts"]:
            assert 0.33 <= alert["utilization_pct"] < 0.67
    
    def test_get_historical_contribution(self, client, mocker):
        """Test historical contribution endpoint."""
        mocker.patch("web.api.debate_data_api.get_current_session", return_value=mocker.Mock())
        
        mock_attribution_engine = mocker.AsyncMock()
        mocker.patch("merid.prediction.pnl_attribution.get_pnl_attribution_engine", return_value=mock_attribution_engine)
        
        response = client.get("/debates/historical-contribution?agent_id=test-agent&days_back=7&points=6")
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["agent_id"] == "test-agent"
        assert data["window_days"] == 7
        assert "points" in data
        assert len(data["points"]) == 6
        
        # Check point structure
        point = data["points"][0]
        assert "timestamp" in point
        assert "debate_contribution_pct" in point
        assert "win_rate" in point
        assert "utilization_pct" in point
        
        # Verify chronological order (oldest→newest)
        timestamps = [datetime.fromisoformat(p["timestamp"].replace("Z", "+00:00")) for p in data["points"]]
        assert timestamps == sorted(timestamps)
    
    def test_get_historical_contribution_default_points(self, client, mocker):
        """Test historical contribution with default points calculation."""
        mocker.patch("web.api.debate_data_api.get_current_session", return_value=mocker.Mock())
        
        mock_attribution_engine = mocker.AsyncMock()
        mocker.patch("merid.prediction.pnl_attribution.get_pnl_attribution_engine", return_value=mock_attribution_engine)
        
        response = client.get("/debates/historical-contribution?agent_id=test-agent&days_back=14")
        
        assert response.status_code == 200
        data = response.json()
        
        # Should use default points calculation (6–20 based on days)
        assert 6 <= len(data["points"]) <= 20
    
    def test_get_debate_rollups_team(self, client, mocker):
        """Test rollups endpoint grouped by team."""
        mocker.patch("web.api.debate_data_api.get_current_session", return_value=mocker.Mock())
        
        mock_quota_manager = mocker.Mock()
        mock_quota_manager.get_risk_quota_summary.return_value = {
            "agent-1": {"team_id": "team-a"},
            "agent-2": {"team_id": "team-a"},
            "agent-3": {"team_id": "team-b"}
        }
        
        mock_attribution_engine = mocker.AsyncMock()
        mock_attribution_engine.generate_attribution_summary.return_value = mocker.Mock(
            agent_contributions={
                "agent-1": {"debate_contribution_pct": 0.03},
                "agent-2": {"debate_contribution_pct": 0.01},
                "agent-3": {"debate_contribution_pct": -0.02}
            }
        )
        
        mocker.patch("merid.prediction.agent_risk_quotas.get_agent_risk_quota_manager", return_value=mock_quota_manager)
        mocker.patch("merid.prediction.pnl_attribution.get_pnl_attribution_engine", return_value=mock_attribution_engine)
        
        response = client.get("/debates/rollups?group_by=team&days_back=7")
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["group_by"] == "team"
        assert data["window_days"] == 7
        assert "rows" in data
        
        # Should have rows for both teams
        team_ids = {row["id"] for row in data["rows"]}
        assert "team-a" in team_ids
        assert "team-b" in team_ids
        
        # Check row structure
        row = data["rows"][0]
        assert "id" in row
        assert "label" in row
        assert "debate_contribution_pct" in row
        assert "sharpe_delta" in row
        assert "drawdown_delta" in row
        assert "agents" in row
        assert "utilization_pct" in row
        
        # Verify team-a has both agents
        team_a_row = next(row for row in data["rows"] if row["id"] == "team-a")
        assert set(team_a_row["agents"]) == {"agent-1", "agent-2"}
        
        # Verify sorting by contribution (highest first)
        contributions = [row["debate_contribution_pct"] for row in data["rows"]]
        assert contributions == sorted(contributions, reverse=True)
    
    def test_get_debate_rollups_strategy(self, client, mocker):
        """Test rollups endpoint grouped by strategy (using tier as proxy)."""
        mocker.patch("web.api.debate_data_api.get_current_session", return_value=mocker.Mock())
        
        mock_quota_manager = mocker.Mock()
        mock_quota_manager.get_risk_quota_summary.return_value = {
            "agent-1": {"tier": "gold"},
            "agent-2": {"tier": "gold"},
            "agent-3": {"tier": "silver"}
        }
        
        mock_attribution_engine = mocker.AsyncMock()
        mock_attribution_engine.generate_attribution_summary.return_value = mocker.Mock(
            agent_contributions={
                "agent-1": {"debate_contribution_pct": 0.03},
                "agent-2": {"debate_contribution_pct": 0.02},
                "agent-3": {"debate_contribution_pct": 0.01}
            }
        )
        
        mocker.patch("merid.prediction.agent_risk_quotas.get_agent_risk_quota_manager", return_value=mock_quota_manager)
        mocker.patch("merid.prediction.pnl_attribution.get_pnl_attribution_engine", return_value=mock_attribution_engine)
        
        response = client.get("/debates/rollups?group_by=strategy&days_back=7")
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["group_by"] == "strategy"
        
        # Should have rows for gold and silver tiers
        strategy_ids = {row["id"] for row in data["rows"]}
        assert "gold" in strategy_ids
        assert "silver" in strategy_ids
        
        # Gold strategy should have both gold agents
        gold_row = next(row for row in data["rows"] if row["id"] == "gold")
        assert set(gold_row["agents"]) == {"agent-1", "agent-2"}
    
    def test_get_debate_rollups_configuration(self, client, mocker):
        """Test rollups endpoint with configuration grouping (all agents)."""
        mocker.patch("web.api.debate_data_api.get_current_session", return_value=mocker.Mock())
        
        mock_quota_manager = mocker.Mock()
        mock_quota_manager.get_risk_quota_summary.return_value = {}
        
        mock_attribution_engine = mocker.AsyncMock()
        mock_attribution_engine.generate_attribution_summary.return_value = mocker.Mock(
            agent_contributions={
                "agent-1": {"debate_contribution_pct": 0.03},
                "agent-2": {"debate_contribution_pct": 0.01}
            }
        )
        
        mocker.patch("merid.prediction.agent_risk_quotas.get_agent_risk_quota_manager", return_value=mock_quota_manager)
        mocker.patch("merid.prediction.pnl_attribution.get_pnl_attribution_engine", return_value=mock_attribution_engine)
        
        response = client.get("/debates/rollups?group_by=configuration&days_back=7")
        
        if response.status_code != 200:
            print(f"Error response: {response.status_code}")
            print(f"Response body: {response.text}")
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["group_by"] == "configuration"
        assert len(data["rows"]) == 1
        assert data["rows"][0]["id"] == "all_agents"
        assert set(data["rows"][0]["agents"]) == {"agent-1", "agent-2"}
    
    def test_error_handling(self, client, mocker):
        """Test error handling in endpoints."""
        mocker.patch("web.api.debate_data_api.get_current_session", return_value=mocker.Mock())
        
        # Mock dependency to raise exception
        mocker.patch("merid.prediction.agent_risk_quotas.get_agent_risk_quota_manager",
                    side_effect=Exception("Database error"))
        
        response = client.get("/debates/alerts")
        
        assert response.status_code == 500
        assert "Failed to get debate alerts" in response.json()["detail"]
    
    def test_contract_guarantees(self, client, mocker):
        """Test that endpoints meet contract guarantees (determinism, ordering)."""
        mocker.patch("web.api.debate_data_api.get_current_session", return_value=mocker.Mock())
        
        # Test alerts ordering (newest→oldest)
        mock_quota_manager = mocker.Mock()
        mock_quota_manager.get_risk_quota_summary.return_value = {
            "agent-1": {"tier": "gold", "utilization_pct": 0.95}
        }
        
        mock_attribution_engine = mocker.AsyncMock()
        mock_attribution_engine.generate_attribution_summary.return_value = mocker.Mock(
            agent_contributions={"agent-1": {"debate_contribution_pct": -0.01}}
        )
        
        mocker.patch("merid.prediction.agent_risk_quotas.get_agent_risk_quota_manager", return_value=mock_quota_manager)
        mocker.patch("merid.prediction.pnl_attribution.get_pnl_attribution_engine", return_value=mock_attribution_engine)
        
        response = client.get("/debates/alerts")
        data = response.json()
        
        # Verify newest→oldest ordering
        timestamps = [datetime.fromisoformat(alert["triggered_at"].replace("Z", "+00:00")) 
                     for alert in data["alerts"]]
        assert timestamps == sorted(timestamps, reverse=True)
        
        # Test deterministic responses (same parameters → same results)
        response2 = client.get("/debates/alerts")
        data2 = response2.json()
        
        # Should be identical (within reasonable time tolerance for generated_at)
        assert len(data["alerts"]) == len(data2["alerts"])
        for i, (alert1, alert2) in enumerate(zip(data["alerts"], data2["alerts"])):
            # Skip timestamp comparison as it includes generated_at
            assert alert1["agent_id"] == alert2["agent_id"]
            assert alert1["severity"] == alert2["severity"]
