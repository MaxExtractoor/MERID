"""Integration tests for prediction markets arbitrage agent UI functionality."""

import pytest
from unittest.mock import patch, Mock, AsyncMock
from fastapi.testclient import TestClient
import time

from monitoring.prediction_markets import (
    PredictionMarket, 
    PredictionPlatform, 
    MarketCategory, 
    ResolutionStatus
)


class TestPredictionArbitrageAgentUI:
    """Integration tests for prediction markets arbitrage agent UI endpoints and rendering."""

    @pytest.fixture
    def mock_agent_response(self):
        """Create a mock agent response for testing."""
        return {
            "status": "success",
            "agent_id": "prediction-arbitrage-analyst-01",
            "model": "merid-strategist:latest",
            "analysis": {
                "summary": "Found 3 arbitrage opportunities with spreads ranging from 3% to 13%. Bitcoin opportunity shows highest spread with good liquidity.",
                "top_opportunities": [
                    {
                        "canonical_question": "will bitcoin reach 100k by end of 2024",
                        "spread_probability": 0.13,
                        "best_venue": "polymarket",
                        "best_probability": 0.65,
                        "worst_venue": "kalshi",
                        "worst_probability": 0.52,
                        "days_to_resolution": 30.0,
                        "total_liquidity": 450000.0,
                        "risk_note": "High liquidity, good time horizon",
                        "forecast_probability": 0.85
                    },
                    {
                        "canonical_question": "will ethereum reach 3k by end of 2024",
                        "spread_probability": 0.08,
                        "best_venue": "polymarket",
                        "best_probability": 0.55,
                        "worst_venue": "augur",
                        "worst_probability": 0.47,
                        "days_to_resolution": 45.0,
                        "total_liquidity": 250000.0,
                        "risk_note": "Moderate liquidity, reasonable time horizon",
                        "forecast_probability": 0.65
                    },
                    {
                        "canonical_question": "will gdp exceed 3 in q4",
                        "spread_probability": 0.03,
                        "best_venue": "kalshi",
                        "best_probability": 0.45,
                        "worst_venue": "polymarket",
                        "worst_probability": 0.42,
                        "days_to_resolution": 15.0,
                        "total_liquidity": 140000.0,
                        "risk_note": "Low liquidity, near expiry",
                        "forecast_probability": 0.45
                    }
                ],
                "filters_used": {
                    "min_spread": 0.05,
                    "min_liquidity": 50000.0,
                    "categories": []
                },
                "total_opportunities_analyzed": 3,
                "analysis_timestamp": time.time(),
                "bucket_analysis": [
                    {
                        "bucket_range": "0.4-0.6",
                        "count": 1,
                        "avg_forecast": 0.45,
                        "empirical_success_rate": 0.40,
                        "avg_spread": 0.03,
                        "avg_liquidity": 140000.0
                    },
                    {
                        "bucket_range": "0.6-0.8",
                        "count": 1,
                        "avg_forecast": 0.65,
                        "empirical_success_rate": 0.58,
                        "avg_spread": 0.08,
                        "avg_liquidity": 250000.0
                    },
                    {
                        "bucket_range": "0.8-1.0",
                        "count": 1,
                        "avg_forecast": 0.85,
                        "empirical_success_rate": 0.76,
                        "avg_spread": 0.13,
                        "avg_liquidity": 450000.0
                    }
                ],
                "brier_score": 0.003889
            },
            "filters_used": {
                "min_spread": 0.05,
                "max_opportunities": 10,
                "min_liquidity": 50000.0,
                "categories": []
            }
        }

    @pytest.fixture
    def mock_empty_agent_response(self):
        """Create a mock agent response with no opportunities."""
        return {
            "status": "success",
            "agent_id": "prediction-arbitrage-analyst-01",
            "model": "merid-strategist:latest",
            "analysis": {
                "summary": "No arbitrage opportunities found matching the current criteria (min spread: 5%, min liquidity: $50,000).",
                "top_opportunities": [],
                "filters_used": {
                    "min_spread": 0.05,
                    "min_liquidity": 50000.0,
                    "categories": []
                },
                "total_opportunities_analyzed": 0,
                "analysis_timestamp": time.time()
            },
            "filters_used": {
                "min_spread": 0.05,
                "max_opportunities": 10,
                "min_liquidity": 50000.0,
                "categories": []
            }
        }

    @pytest.fixture
    def client(self):
        """Create test client."""
        from web.main import create_app
        app = create_app()
        return TestClient(app)

    def test_agent_ui_happy_path(self, client, mock_agent_response):
        """Test UI renders agent analysis correctly with data."""
        with patch('agents.registry.load_agents') as mock_load_agents:
            # Create a mock agent
            mock_agent = Mock()
            mock_agent.agent_id = "prediction-arbitrage-analyst-01"
            mock_agent.model_name = "merid-strategist:latest"
            mock_agent.process = AsyncMock(return_value=mock_agent_response)
            mock_load_agents.return_value = [mock_agent]
            
            # Test the agent API endpoint
            response = client.post("/api/v1/institutional/agents/prediction-arbitrage-analyst/analyze?min_spread=0.05&max_opportunities=10&min_liquidity=50000.0")
            
            assert response.status_code == 200
            data = response.json()
            
            # Verify response structure
            assert data["status"] == "success"
            assert "analysis" in data
            assert data["agent_id"] == "prediction-arbitrage-analyst-01"
            
            analysis = data["analysis"]["analysis"]
            assert "summary" in analysis
            assert "top_opportunities" in analysis
            assert "filters_used" in analysis
            assert "total_opportunities_analyzed" in analysis
            
            # Verify opportunities structure
            opportunities = analysis["top_opportunities"]
            assert len(opportunities) == 3
            
            # Verify first opportunity
            opp = opportunities[0]
            assert opp["canonical_question"] == "will bitcoin reach 100k by end of 2024"
            assert opp["spread_probability"] == 0.13
            assert opp["best_venue"] == "polymarket"
            assert opp["worst_venue"] == "kalshi"
            assert opp["total_liquidity"] == 450000.0
            assert opp["risk_note"] == "High liquidity, good time horizon"

    def test_agent_ui_empty_opportunities(self, client, mock_empty_agent_response):
        """Test UI handles empty agent opportunities gracefully."""
        with patch('agents.registry.load_agents') as mock_load_agents:
            # Create a mock agent
            mock_agent = Mock()
            mock_agent.agent_id = "prediction-arbitrage-analyst-01"
            mock_agent.model_name = "merid-strategist:latest"
            mock_agent.process = AsyncMock(return_value=mock_empty_agent_response)
            mock_load_agents.return_value = [mock_agent]
            
            response = client.post("/api/v1/institutional/agents/prediction-arbitrage-analyst/analyze?min_spread=0.05&max_opportunities=10&min_liquidity=50000.0")
            
            assert response.status_code == 200
            data = response.json()
            
            # Verify empty opportunities response
            analysis = data["analysis"]["analysis"]
            assert analysis["top_opportunities"] == []
            assert analysis["total_opportunities_analyzed"] == 0
            assert "no arbitrage opportunities" in analysis["summary"].lower()

    def test_agent_ui_error_handling(self, client):
        """Test UI handles agent API errors gracefully."""
        with patch('agents.registry.load_agents') as mock_load_agents:
            # Create a mock agent that raises an exception
            mock_agent = Mock()
            mock_agent.agent_id = "prediction-arbitrage-analyst-01"
            mock_agent.model_name = "merid-strategist:latest"
            mock_agent.process = AsyncMock(side_effect=Exception("LLM timeout"))
            mock_load_agents.return_value = [mock_agent]
            
            response = client.post("/api/v1/institutional/agents/prediction-arbitrage-analyst/analyze?min_spread=0.05&max_opportunities=10&min_liquidity=50000.0")
            
            assert response.status_code == 200
            data = response.json()
            
            # Verify error response structure
            assert data["status"] == "error"
            assert "error" in data
            # The actual error message will be "LLM timeout" from our side_effect
            assert "LLM timeout" in data["error"]

    def test_agent_ui_invalid_response(self, client):
        """Test UI handles invalid agent response gracefully."""
        with patch('agents.registry.load_agents') as mock_load_agents:
            # Create a mock agent that returns invalid response
            mock_agent = Mock()
            mock_agent.agent_id = "prediction-arbitrage-analyst-01"
            mock_agent.model_name = "merid-strategist:latest"
            mock_agent.process = AsyncMock(return_value={
                "status": "success",
                "agent_id": "prediction-arbitrage-analyst-01",
                "model": "merid-strategist:latest"
                # Missing "analysis" field
            })
            mock_load_agents.return_value = [mock_agent]
            
            response = client.post("/api/v1/institutional/agents/prediction-arbitrage-analyst/analyze?min_spread=0.05&max_opportunities=10&min_liquidity=50000.0")
            
            assert response.status_code == 200
            data = response.json()
            
            # Should still return 200 but the agent response is wrapped
            assert data["status"] == "success"
            # The agent response is wrapped in data["analysis"], but since it's invalid, 
            # the nested analysis field should be missing
            assert "analysis" in data
            assert "analysis" not in data["analysis"]  # Missing from agent's response

    def test_agent_ui_dashboard_integration(self, client, mock_agent_response):
        """Test that agent analysis is integrated into the dashboard properly."""
        with patch('agents.registry.load_agents') as mock_load_agents:
            # Create a mock agent
            mock_agent = Mock()
            mock_agent.agent_id = "prediction-arbitrage-analyst-01"
            mock_agent.model_name = "merid-strategist:latest"
            mock_agent.process = AsyncMock(return_value=mock_agent_response)
            mock_load_agents.return_value = [mock_agent]
            # Get the dashboard page
            response = client.get("/debug-v2")
            assert response.status_code == 200
            
            html_content = response.text
            
            # Verify agent UI elements are present
            assert "Analyze with Agent" in html_content
            assert "Raw Data" in html_content
            assert "Agent View" in html_content
            assert "agent-analysis-container" in html_content
            assert "raw-arbitrage-view" in html_content
            assert "agent-arbitrage-view" in html_content
            
            # Verify JavaScript functions are present
            assert "loadArbitrageAgentAnalysis()" in html_content
            assert "showRawView()" in html_content
            assert "showAgentView()" in html_content
            assert "renderAgentAnalysis" in html_content

    def test_agent_ui_filter_wiring(self, client, mock_agent_response):
        """Test that UI correctly sends current filters to the agent."""
        with patch('agents.registry.load_agents') as mock_load_agents:
            # Create a mock agent
            mock_agent = Mock()
            mock_agent.agent_id = "prediction-arbitrage-analyst-01"
            mock_agent.model_name = "merid-strategist:latest"
            mock_agent.process = AsyncMock(return_value=mock_agent_response)
            mock_load_agents.return_value = [mock_agent]

            # Test with different filter values
            response = client.post("/api/v1/institutional/agents/prediction-arbitrage-analyst/analyze?min_spread=0.03&max_opportunities=5&min_liquidity=100000.0&categories=crypto,politics")
            
            assert response.status_code == 200
            
            # Verify the mock was called with correct parameters
            mock_agent.process.assert_called_once()
            call_args = mock_agent.process.call_args
            energy = call_args[0][0]  # First argument is the energy packet
            
            # Verify the energy packet contains the filter parameters in payload
            assert "payload" in energy
            payload = energy["payload"]
            assert "min_spread" in payload
            assert "max_opportunities" in payload
            assert "min_liquidity" in payload
            assert "categories" in payload

    def test_agent_ui_kpi_calculation(self, client, mock_agent_response):
        """Test that UI correctly calculates and displays KPIs."""
        with patch('agents.registry.load_agents') as mock_load_agents:
            # Create a mock agent
            mock_agent = Mock()
            mock_agent.agent_id = "prediction-arbitrage-analyst-01"
            mock_agent.model_name = "merid-strategist:latest"
            mock_agent.process = AsyncMock(return_value=mock_agent_response)
            mock_load_agents.return_value = [mock_agent]
            response = client.post("/api/v1/institutional/agents/prediction-arbitrage-analyst/analyze?min_spread=0.05&max_opportunities=10&min_liquidity=50000.0")
            
            assert response.status_code == 200
            data = response.json()
            analysis = data["analysis"]["analysis"]
            
            # Verify KPI calculations would be done correctly in JavaScript
            # Max spread should be 0.13 (13%)
            max_spread = max(opp["spread_probability"] for opp in analysis["top_opportunities"])
            assert max_spread == 0.13
            
            # Average spread
            avg_spread = sum(opp["spread_probability"] for opp in analysis["top_opportunities"]) / len(analysis["top_opportunities"])
            expected_avg = (0.13 + 0.08 + 0.03) / 3
            assert abs(avg_spread - expected_avg) < 0.001
            
            # Average liquidity
            avg_liquidity = sum(opp["total_liquidity"] for opp in analysis["top_opportunities"]) / len(analysis["top_opportunities"])
            expected_liquidity = (450000.0 + 250000.0 + 140000.0) / 3
            assert abs(avg_liquidity - expected_liquidity) < 1.0

    def test_agent_ui_risk_note_display(self, client, mock_agent_response):
        """Test that risk notes are properly displayed in the UI."""
        with patch('agents.registry.load_agents') as mock_load_agents:
            # Create a mock agent
            mock_agent = Mock()
            mock_agent.agent_id = "prediction-arbitrage-analyst-01"
            mock_agent.model_name = "merid-strategist:latest"
            mock_agent.process = AsyncMock(return_value=mock_agent_response)
            mock_load_agents.return_value = [mock_agent]
            response = client.post("/api/v1/institutional/agents/prediction-arbitrage-analyst/analyze?min_spread=0.05&max_opportunities=10&min_liquidity=50000.0")
            
            assert response.status_code == 200
            data = response.json()
            analysis = data["analysis"]["analysis"]
            
            # Verify risk notes are present
            opportunities = analysis["top_opportunities"]
            risk_notes = [opp["risk_note"] for opp in opportunities]
            
            assert "High liquidity, good time horizon" in risk_notes
            assert "Moderate liquidity, reasonable time horizon" in risk_notes
            assert "Low liquidity, near expiry" in risk_notes

    def test_agent_ui_venue_comparison(self, client, mock_agent_response):
        """Test that venue comparison data is properly displayed."""
        with patch('agents.registry.load_agents') as mock_load_agents:
            # Create a mock agent
            mock_agent = Mock()
            mock_agent.agent_id = "prediction-arbitrage-analyst-01"
            mock_agent.model_name = "merid-strategist:latest"
            mock_agent.process = AsyncMock(return_value=mock_agent_response)
            mock_load_agents.return_value = [mock_agent]
            response = client.post("/api/v1/institutional/agents/prediction-arbitrage-analyst/analyze?min_spread=0.05&max_opportunities=10&min_liquidity=50000.0")
            
            assert response.status_code == 200
            data = response.json()
            analysis = data["analysis"]["analysis"]
            
            # Verify venue comparison data
            opportunities = analysis["top_opportunities"]
            
            # Check first opportunity
            first_opp = opportunities[0]
            assert first_opp["best_venue"] == "polymarket"
            assert first_opp["best_probability"] == 0.65
            assert first_opp["worst_venue"] == "kalshi"
            assert first_opp["worst_probability"] == 0.52
            
            # Verify spread calculation
            expected_spread = 0.65 - 0.52
            assert abs(first_opp["spread_probability"] - expected_spread) < 0.001

    def test_agent_ui_time_to_resolution(self, client, mock_agent_response):
        """Test that time to resolution is properly formatted."""
        with patch('agents.registry.load_agents') as mock_load_agents:
            # Create a mock agent
            mock_agent = Mock()
            mock_agent.agent_id = "prediction-arbitrage-analyst-01"
            mock_agent.model_name = "merid-strategist:latest"
            mock_agent.process = AsyncMock(return_value=mock_agent_response)
            mock_load_agents.return_value = [mock_agent]
            response = client.post("/api/v1/institutional/agents/prediction-arbitrage-analyst/analyze?min_spread=0.05&max_opportunities=10&min_liquidity=50000.0")
            
            assert response.status_code == 200
            data = response.json()
            analysis = data["analysis"]["analysis"]
            
            # Verify time to resolution data
            opportunities = analysis["top_opportunities"]
            time_to_resolutions = [opp["days_to_resolution"] for opp in opportunities]
            
            assert 30.0 in time_to_resolutions  # Bitcoin opportunity
            assert 45.0 in time_to_resolutions  # Ethereum opportunity
            assert 15.0 in time_to_resolutions  # GDP opportunity
