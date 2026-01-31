"""Tests for PredictionArbitrageAnalystAgent."""

import json
import pytest
import time
from unittest.mock import AsyncMock, Mock, patch
import httpx

from agents.base_agent import BaseAgent, AgentErrorResponse, AgentErrorType
from agents.prediction_arbitrage_analyst import PredictionArbitrageAnalystAgent, ArbitrageOpportunitySummary, ArbitrageAnalysisResponse
from monitoring.prediction_markets import PredictionMarket, PredictionPlatform, MarketCategory, ResolutionStatus


class TestPredictionArbitrageAnalyst:
    """Test suite for PredictionArbitrageAnalystAgent."""

    @pytest.fixture
    def agent(self):
        """Create a test arbitrage analyst agent."""
        return PredictionArbitrageAnalystAgent(
            agent_id="test-arbitrage-analyst-01",
            model_name="test-model:latest",
            min_spread=0.05,
            max_opportunities=5,
            min_liquidity=50000.0
        )

    @pytest.fixture
    def sample_energy(self):
        """Sample energy packet for testing."""
        return {
            "energy_id": "test-energy-123",
            "source": "test",
            "payload": "Test payload for arbitrage analysis",
        }

    @pytest.fixture
    def mock_arbitrage_opportunities(self):
        """Create mock arbitrage opportunities for testing."""
        return [
            {
                "canonical_question": "will bitcoin reach 100k by end of 2024",
                "spread_probability": 0.13,
                "max_probability": 0.65,
                "min_probability": 0.52,
                "max_probability_venue": "polymarket",
                "min_probability_venue": "kalshi",
                "markets": [
                    {
                        "venue": "polymarket",
                        "market_id": "poly_001",
                        "implied_probability": 0.65,
                        "liquidity": 250000.0,
                        "days_to_resolution": 30.0,
                        "category": "crypto"
                    },
                    {
                        "venue": "kalshi",
                        "market_id": "kalshi_001",
                        "implied_probability": 0.52,
                        "liquidity": 200000.0,
                        "days_to_resolution": 30.0,
                        "category": "crypto"
                    }
                ]
            },
            {
                "canonical_question": "will ethereum reach 3k by end of 2024",
                "spread_probability": 0.08,
                "max_probability": 0.55,
                "min_probability": 0.47,
                "max_probability_venue": "polymarket",
                "min_probability_venue": "augur",
                "markets": [
                    {
                        "venue": "polymarket",
                        "market_id": "poly_eth_001",
                        "implied_probability": 0.55,
                        "liquidity": 150000.0,
                        "days_to_resolution": 45.0,
                        "category": "crypto"
                    },
                    {
                        "venue": "augur",
                        "market_id": "augur_eth_001",
                        "implied_probability": 0.47,
                        "liquidity": 100000.0,
                        "days_to_resolution": 45.0,
                        "category": "crypto"
                    }
                ]
            },
            {
                "canonical_question": "will gdp exceed 3 in q4",
                "spread_probability": 0.03,
                "max_probability": 0.45,
                "min_probability": 0.42,
                "max_probability_venue": "kalshi",
                "min_probability_venue": "polymarket",
                "markets": [
                    {
                        "venue": "kalshi",
                        "market_id": "kalshi_gdp_001",
                        "implied_probability": 0.45,
                        "liquidity": 80000.0,
                        "days_to_resolution": 15.0,
                        "category": "economics"
                    },
                    {
                        "venue": "polymarket",
                        "market_id": "poly_gdp_001",
                        "implied_probability": 0.42,
                        "liquidity": 60000.0,
                        "days_to_resolution": 15.0,
                        "category": "economics"
                    }
                ]
            }
        ]

    @pytest.mark.asyncio
    async def test_successful_analysis_with_opportunities(self, agent, sample_energy, mock_arbitrage_opportunities):
        """Test successful arbitrage analysis with deterministic opportunities."""
        # Mock the analytics function
        with patch('monitoring.prediction_analytics.get_arbitrage_opportunities') as mock_get_opps:
            # Create mock ArbitrageOpportunity objects
            from monitoring.prediction_analytics import ArbitrageOpportunity
            mock_opp_objects = []
            for opp_data in mock_arbitrage_opportunities:
                opp = ArbitrageOpportunity(
                    canonical_question=opp_data["canonical_question"],
                    markets=opp_data["markets"],
                    max_probability=opp_data["max_probability"],
                    min_probability=opp_data["min_probability"],
                    spread_probability=opp_data["spread_probability"],
                    max_probability_venue=opp_data["max_probability_venue"],
                    min_probability_venue=opp_data["min_probability_venue"]
                )
                mock_opp_objects.append(opp)
            
            mock_get_opps.return_value = mock_opp_objects
            
            # Mock LLM response
            mock_response_data = {
                "response": json.dumps({
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
                            "risk_note": "High liquidity, good time horizon"
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
                            "risk_note": "Moderate liquidity, reasonable time horizon"
                        }
                    ],
                    "filters_used": {"min_spread": 0.05, "min_liquidity": 50000.0},
                    "total_opportunities_analyzed": 3,
                    "analysis_timestamp": time.time()
                })
            }
            
            # Mock the httpx.AsyncClient context manager properly
            with patch('httpx.AsyncClient') as mock_client_class:
                mock_client = AsyncMock()
                # Use regular Mock for response to avoid making json() async
                mock_response = Mock()
                mock_response.json.return_value = mock_response_data
                mock_client.post.return_value = mock_response
                mock_client_class.return_value.__aenter__.return_value = mock_client
                mock_client_class.return_value.__aexit__.return_value = None
                
                # Process the energy
                result = await agent.process(sample_energy, phase="analysis")
                
                # Verify structured response
                analysis = result["analysis"]
                assert "summary" in analysis
                assert "top_opportunities" in analysis
                assert "filters_used" in analysis
                assert "total_opportunities_analyzed" in analysis
                assert "analysis_timestamp" in analysis
                
                # Verify top opportunities structure
                top_opps = analysis["top_opportunities"]
                assert len(top_opps) == 2  # Only opportunities above min_spread threshold
                
                # Verify first opportunity (highest spread)
                first_opp = top_opps[0]
                assert first_opp["canonical_question"] == "will bitcoin reach 100k by end of 2024"
                assert first_opp["spread_probability"] == 0.13
                assert first_opp["best_venue"] == "polymarket"
                assert first_opp["worst_venue"] == "kalshi"
                assert first_opp["total_liquidity"] == 450000.0
                
                # Verify filters used
                filters = analysis["filters_used"]
                assert filters["min_spread"] == 0.05
                assert filters["min_liquidity"] == 50000.0

    @pytest.mark.asyncio
    async def test_no_opportunities_case(self, agent, sample_energy):
        """Test agent behavior when no arbitrage opportunities are found."""
        # Mock empty analytics response
        with patch('monitoring.prediction_analytics.get_arbitrage_opportunities') as mock_get_opps:
            mock_get_opps.return_value = []
            
            # Mock LLM response for no opportunities
            mock_response_data = {
                "response": json.dumps({
                    "summary": "No arbitrage opportunities found matching the current criteria (min spread: 5%, min liquidity: $50,000).",
                    "top_opportunities": [],
                    "filters_used": {"min_spread": 0.05, "min_liquidity": 50000.0},
                    "total_opportunities_analyzed": 0,
                    "analysis_timestamp": time.time()
                })
            }
            
            with patch('httpx.AsyncClient') as mock_client_class:
                mock_client = AsyncMock()
                mock_response = Mock()
                mock_response.json.return_value = mock_response_data
                mock_client.post.return_value = mock_response
                mock_client_class.return_value.__aenter__.return_value = mock_client
                mock_client_class.return_value.__aexit__.return_value = None
                
                # Process the energy
                result = await agent.process(sample_energy, phase="analysis")
                
                # Verify empty opportunities response
                analysis = result["analysis"]
                assert analysis["summary"] is not None
                assert len(analysis["top_opportunities"]) == 0
                assert analysis["total_opportunities_analyzed"] == 0
                assert "no arbitrage opportunities" in analysis["summary"].lower()

    @pytest.mark.asyncio
    async def test_analytics_failure_path(self, agent, sample_energy):
        """Test agent behavior when analytics function fails."""
        # Mock analytics failure
        with patch('monitoring.prediction_analytics.get_arbitrage_opportunities') as mock_get_opps:
            mock_get_opps.side_effect = Exception("Analytics service unavailable")
            
            # Mock LLM response for analytics failure
            mock_response_data = {
                "response": json.dumps({
                    "summary": "Unable to analyze arbitrage opportunities due to analytics service failure.",
                    "top_opportunities": [],
                    "filters_used": {"min_spread": 0.05, "min_liquidity": 50000.0},
                    "total_opportunities_analyzed": 0,
                    "analysis_timestamp": time.time()
                })
            }
            
            with patch('httpx.AsyncClient') as mock_client_class:
                mock_client = AsyncMock()
                mock_response = Mock()
                mock_response.json.return_value = mock_response_data
                mock_client.post.return_value = mock_response
                mock_client_class.return_value.__aenter__.return_value = mock_client
                mock_client_class.return_value.__aexit__.return_value = None
                
                # Process the energy
                result = await agent.process(sample_energy, phase="analysis")
                
                # Verify error handling response
                analysis = result["analysis"]
                assert analysis["summary"] is not None
                assert len(analysis["top_opportunities"]) == 0
                assert analysis["total_opportunities_analyzed"] == 0
                assert "unable to analyze" in analysis["summary"].lower()

    @pytest.mark.asyncio
    async def test_llm_failure_path(self, agent, sample_energy, mock_arbitrage_opportunities):
        """Test agent behavior when LLM call fails."""
        # Mock the analytics function
        with patch('monitoring.prediction_analytics.get_arbitrage_opportunities') as mock_get_opps:
            from monitoring.prediction_analytics import ArbitrageOpportunity
            mock_opp_objects = []
            for opp_data in mock_arbitrage_opportunities:
                opp = ArbitrageOpportunity(
                    canonical_question=opp_data["canonical_question"],
                    markets=opp_data["markets"],
                    max_probability=opp_data["max_probability"],
                    min_probability=opp_data["min_probability"],
                    spread_probability=opp_data["spread_probability"],
                    max_probability_venue=opp_data["max_probability_venue"],
                    min_probability_venue=opp_data["min_probability_venue"]
                )
                mock_opp_objects.append(opp)
            
            mock_get_opps.return_value = mock_opp_objects
            
            # Mock LLM timeout
            with patch('httpx.AsyncClient') as mock_client_class:
                mock_client = AsyncMock()
                mock_client.post.side_effect = httpx.RequestError("Connection timeout")
                mock_client_class.return_value.__aenter__.return_value = mock_client
                mock_client_class.return_value.__aexit__.return_value = None
                
                # Process should raise structured error
                with pytest.raises(AgentErrorResponse) as exc_info:
                    await agent.process(sample_energy, phase="analysis")
                
                # Verify structured error response
                error = exc_info.value
                assert error.error_type == AgentErrorType.CONNECTION
                assert "Connection timeout" in error.message
                assert error.details["agent_id"] == agent.agent_id
                assert error.details["model_name"] == agent.model_name

    @pytest.mark.asyncio
    async def test_llm_invalid_json_response(self, agent, sample_energy, mock_arbitrage_opportunities):
        """Test agent behavior when LLM returns invalid JSON."""
        # Mock the analytics function
        with patch('monitoring.prediction_analytics.get_arbitrage_opportunities') as mock_get_opps:
            from monitoring.prediction_analytics import ArbitrageOpportunity
            mock_opp_objects = []
            for opp_data in mock_arbitrage_opportunities:
                opp = ArbitrageOpportunity(
                    canonical_question=opp_data["canonical_question"],
                    markets=opp_data["markets"],
                    max_probability=opp_data["max_probability"],
                    min_probability=opp_data["min_probability"],
                    spread_probability=opp_data["spread_probability"],
                    max_probability_venue=opp_data["max_probability_venue"],
                    min_probability_venue=opp_data["min_probability_venue"]
                )
                mock_opp_objects.append(opp)
            
            mock_get_opps.return_value = mock_opp_objects
            
            # Mock LLM response with invalid JSON
            mock_response_data = {
                "response": "This is not valid JSON response from LLM"
            }
            
            with patch('httpx.AsyncClient') as mock_client_class:
                mock_client = AsyncMock()
                mock_response = Mock()
                mock_response.json.return_value = mock_response_data
                mock_client.post.return_value = mock_response
                mock_client_class.return_value.__aenter__.return_value = mock_client
                mock_client_class.return_value.__aexit__.return_value = None
                
                # Process the energy
                result = await agent.process(sample_energy, phase="analysis")
                
                # Verify fallback response for JSON parsing error
                analysis = result["analysis"]
                assert analysis["summary"] is not None
                assert "response parsing failed" in analysis["summary"].lower()
                assert len(analysis["top_opportunities"]) == 0
                assert "error" in analysis

    @pytest.mark.asyncio
    async def test_filtering_by_liquidity(self, agent, sample_energy):
        """Test that agent properly filters opportunities by liquidity."""
        # Create opportunities with different liquidity levels
        low_liquidity_opp = {
            "canonical_question": "low liquidity opportunity",
            "spread_probability": 0.10,
            "max_probability": 0.60,
            "min_probability": 0.50,
            "max_probability_venue": "polymarket",
            "min_probability_venue": "kalshi",
            "markets": [
                {
                    "venue": "polymarket",
                    "implied_probability": 0.60,
                    "liquidity": 30000.0,  # Below min_liquidity threshold
                    "days_to_resolution": 20.0,
                    "category": "crypto"
                },
                {
                    "venue": "kalshi",
                    "implied_probability": 0.50,
                    "liquidity": 25000.0,  # Below min_liquidity threshold
                    "days_to_resolution": 20.0,
                    "category": "crypto"
                }
            ]
        }
        
        high_liquidity_opp = {
            "canonical_question": "high liquidity opportunity",
            "spread_probability": 0.08,
            "max_probability": 0.55,
            "min_probability": 0.47,
            "max_probability_venue": "polymarket",
            "min_probability_venue": "augur",
            "markets": [
                {
                    "venue": "polymarket",
                    "implied_probability": 0.55,
                    "liquidity": 150000.0,  # Above min_liquidity threshold
                    "days_to_resolution": 30.0,
                    "category": "crypto"
                },
                {
                    "venue": "augur",
                    "implied_probability": 0.47,
                    "liquidity": 100000.0,  # Above min_liquidity threshold
                    "days_to_resolution": 30.0,
                    "category": "crypto"
                }
            ]
        }
        
        with patch('monitoring.prediction_analytics.get_arbitrage_opportunities') as mock_get_opps:
            from monitoring.prediction_analytics import ArbitrageOpportunity
            mock_opp_objects = []
            
            for opp_data in [low_liquidity_opp, high_liquidity_opp]:
                opp = ArbitrageOpportunity(
                    canonical_question=opp_data["canonical_question"],
                    markets=opp_data["markets"],
                    max_probability=opp_data["max_probability"],
                    min_probability=opp_data["min_probability"],
                    spread_probability=opp_data["spread_probability"],
                    max_probability_venue=opp_data["max_probability_venue"],
                    min_probability_venue=opp_data["min_probability_venue"]
                )
                mock_opp_objects.append(opp)
            
            mock_get_opps.return_value = mock_opp_objects
            
            # Mock LLM response
            mock_response_data = {
                "response": json.dumps({
                    "summary": "Found 1 arbitrage opportunity after liquidity filtering.",
                    "top_opportunities": [
                        {
                            "canonical_question": "high liquidity opportunity",
                            "spread_probability": 0.08,
                            "best_venue": "polymarket",
                            "best_probability": 0.55,
                            "worst_venue": "augur",
                            "worst_probability": 0.47,
                            "days_to_resolution": 30.0,
                            "total_liquidity": 250000.0,
                            "risk_note": "High liquidity, good time horizon"
                        }
                    ],
                    "filters_used": {"min_spread": 0.05, "min_liquidity": 50000.0},
                    "total_opportunities_analyzed": 1,
                    "analysis_timestamp": time.time()
                })
            }
            
            with patch('httpx.AsyncClient') as mock_client_class:
                mock_client = AsyncMock()
                mock_response = Mock()
                mock_response.json.return_value = mock_response_data
                mock_client.post.return_value = mock_response
                mock_client_class.return_value.__aenter__.return_value = mock_client
                mock_client_class.return_value.__aexit__.return_value = None
                
                # Process the energy
                result = await agent.process(sample_energy, phase="analysis")
                
                # Verify only high liquidity opportunity is included
                analysis = result["analysis"]
                top_opps = analysis["top_opportunities"]
                assert len(top_opps) == 1
                assert top_opps[0]["canonical_question"] == "high liquidity opportunity"
                assert top_opps[0]["total_liquidity"] == 250000.0

    def test_risk_note_generation(self, agent):
        """Test risk note generation for different scenarios."""
        from monitoring.prediction_analytics import ArbitrageOpportunity
        
        # Test high liquidity opportunity
        high_liquidity_opp = ArbitrageOpportunity(
            canonical_question="test question",
            markets=[],
            max_probability=0.65,
            min_probability=0.52,
            spread_probability=0.13,
            max_probability_venue="polymarket",
            min_probability_venue="kalshi"
        )
        
        risk_note = agent._generate_risk_note(high_liquidity_opp, 1500000.0, 30.0)
        assert "High liquidity" in risk_note
        
        # Test low liquidity opportunity
        low_liquidity_opp = ArbitrageOpportunity(
            canonical_question="test question",
            markets=[],
            max_probability=0.60,
            min_probability=0.50,
            spread_probability=0.10,
            max_probability_venue="polymarket",
            min_probability_venue="kalshi"
        )
        
        risk_note = agent._generate_risk_note(low_liquidity_opp, 30000.0, 0.5)
        assert "Low liquidity" in risk_note
        assert "Very near expiry" in risk_note
        
        # Test very high spread opportunity
        high_spread_opp = ArbitrageOpportunity(
            canonical_question="test question",
            markets=[],
            max_probability=0.80,
            min_probability=0.40,
            spread_probability=0.40,
            max_probability_venue="polymarket",
            min_probability_venue="kalshi"
        )
        
        risk_note = agent._generate_risk_note(high_spread_opp, 100000.0, 15.0)
        assert "Very high spread" in risk_note

    def test_agent_configuration(self):
        """Test agent configuration parameters."""
        custom_agent = PredictionArbitrageAnalystAgent(
            agent_id="custom-analyst-01",
            model_name="custom-model:latest",
            min_spread=0.03,
            max_opportunities=15,
            min_liquidity=100000.0,
            categories=["crypto", "politics"]
        )
        
        assert custom_agent.agent_id == "custom-analyst-01"
        assert custom_agent.model_name == "custom-model:latest"
        assert custom_agent.min_spread == 0.03
        assert custom_agent.max_opportunities == 15
        assert custom_agent.min_liquidity == 100000.0
        assert custom_agent.categories == ["crypto", "politics"]
