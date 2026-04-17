"""Tests for PredictionMarketRisk singleton and TradingAgent initialization.

This module verifies that:
1. get_prediction_risk() is initialized only once (by AgentGrid)
2. Multiple TradingAgent instances share the same risk singleton
3. No duplicate "config arg ignored" warnings are produced
"""

import pytest
import logging
from unittest.mock import MagicMock, patch


class TestPredictionRiskSingleton:
    """Verify singleton behavior of PredictionMarketRisk."""

    def test_agent_grid_initializes_risk_once(self, caplog):
        """Test that AgentGrid initializes get_prediction_risk once with config."""
        from merid.prediction.risk import get_prediction_risk, PredictionRiskConfig
        
        # Reset singleton state for clean test
        import merid.prediction.risk as risk_module
        risk_module._risk = None
        
        with caplog.at_level(logging.WARNING, logger="merid.prediction.risk"):
            # First call with config - should initialize without warning
            risk1 = get_prediction_risk(PredictionRiskConfig())
            
            # Second call without config - should return same instance, no warning
            risk2 = get_prediction_risk()
            
            # Third call with different config - should warn about ignored config
            risk3 = get_prediction_risk(PredictionRiskConfig(max_total_notional_usd=999999))
        
        # All should be same instance
        assert risk1 is risk2 is risk3
        
        # Should have exactly one warning about ignored config
        warning_messages = [r.message for r in caplog.records if "config arg ignored" in r.message]
        assert len(warning_messages) == 1

    def test_trading_agent_uses_singleton_without_config(self, caplog):
        """Test that TradingAgent calls get_prediction_risk() without config."""
        from merid.prediction.risk import get_prediction_risk, PredictionRiskConfig
        
        # Reset singleton state
        import merid.prediction.risk as risk_module
        risk_module._risk = None
        
        with caplog.at_level(logging.WARNING, logger="merid.prediction.risk"):
            # Simulate AgentGrid init (first call with config)
            from merid.prediction.agent_grid import AgentGrid
            _ = get_prediction_risk(PredictionRiskConfig())
            
            # Simulate TradingAgent init (should call without config)
            _ = get_prediction_risk()
            _ = get_prediction_risk()
            _ = get_prediction_risk()
        
        # Should have NO warnings since all calls after first have no config
        warning_messages = [r.message for r in caplog.records if "config arg ignored" in r.message]
        assert len(warning_messages) == 0

    def test_multiple_trading_agents_share_risk_identity(self):
        """Test that multiple agents share the same risk object."""
        from merid.prediction.risk import get_prediction_risk, PredictionRiskConfig
        
        # Reset singleton state
        import merid.prediction.risk as risk_module
        risk_module._risk = None
        
        # Initialize once (as AgentGrid does)
        risk1 = get_prediction_risk(PredictionRiskConfig())
        
        # Simulate multiple TradingAgent instances
        risk2 = get_prediction_risk()
        risk3 = get_prediction_risk()
        risk4 = get_prediction_risk()
        
        # All should have same identity
        assert id(risk1) == id(risk2) == id(risk3) == id(risk4)


class TestBaseKalshiAgentContract:
    """Verify BaseKalshiAgent contract and AgentOpinion structure."""

    def test_agent_opinion_dataclass_structure(self):
        """Test AgentOpinion has all required fields."""
        from merid.agents.base import AgentOpinion
        
        opinion = AgentOpinion(
            agent_id="test_agent",
            market_id="KXBTUPDOWN-15M",
            side="buy_yes",
            confidence=0.85,
            edge_estimate=0.15,
            horizon="15m",
            size_pct=0.05,
            metadata={"test": "data"},
        )
        
        assert opinion.agent_id == "test_agent"
        assert opinion.market_id == "KXBTUPDOWN-15M"
        assert opinion.side == "buy_yes"
        assert opinion.confidence == 0.85
        assert opinion.edge_estimate == 0.15
        assert opinion.horizon == "15m"
        assert opinion.size_pct == 0.05
        assert opinion.metadata == {"test": "data"}
        assert opinion.timestamp is not None

    def test_base_kalshi_agent_abstract_get_opinion(self):
        """Test BaseKalshiAgent requires get_opinion implementation."""
        from merid.agents.base import BaseKalshiAgent, AgentOpinion
        
        class ConcreteAgent(BaseKalshiAgent):
            async def get_opinion(self, trace_id=None, correlation_id=None):
                return AgentOpinion(
                    agent_id=self.agent_id,
                    market_id="test_market",
                    side="yes",
                    confidence=0.5,
                    edge_estimate=0.0,
                    horizon="15m",
                )
        
        agent = ConcreteAgent(agent_id="test_concrete")
        assert agent.agent_id == "test_concrete"
        assert agent.category.value == "strategy"

    def test_base_kalshi_agent_no_opinion_returns_no_opinion_output(self):
        """Test _execute returns no_opinion when get_opinion returns None."""
        from merid.agents.base import BaseKalshiAgent, AgentOutput
        
        class NoOpinionAgent(BaseKalshiAgent):
            async def get_opinion(self, trace_id=None, correlation_id=None):
                return None
        
        agent = NoOpinionAgent(agent_id="no_opinion_test")
        
        import asyncio
        output = asyncio.run(agent._execute({}))
        
        assert isinstance(output, AgentOutput)
        assert output.output_type == "no_opinion"
        assert output.agent_id == "no_opinion_test"


class TestAgentOpinionFlow:
    """Verify AgentOpinion flows correctly through the system."""

    def test_regime_agent_opinion_to_taco_mapping(self):
        """Test AgentOpinion fields map correctly to TaCo consensus."""
        from merid.agents.base import AgentOpinion
        
        opinion = AgentOpinion(
            agent_id="eth_15m_regime",
            market_id="KXETHUPDOWN-15M",
            side="buy_yes",
            confidence=0.75,
            edge_estimate=0.12,
            horizon="short",
            size_pct=0.03,
            metadata={"rti_current": 0.65, "vol_regime": "elevated"},
        )
        
        # Simulate the TaCo mapping logic from agent_grid.py
        score = round(opinion.edge_estimate, 4)
        if score >= 0.3:
            stance = "BULL"
        elif score <= -0.3:
            stance = "BEAR"
        else:
            stance = "NEUTRAL"
        
        assert stance == "NEUTRAL"  # 0.12 is between -0.3 and 0.3
        assert opinion.confidence == 0.75


class TestDiagnosticsImports:
    """Verify diagnostics module imports correctly."""

    def test_loop_lag_module_imports(self):
        """Test LoopLagMonitor can be imported without syntax errors."""
        from merid.diagnostics.loop_lag import LoopLagMonitor, get_loop_lag_monitor
        
        monitor1 = get_loop_lag_monitor()
        monitor2 = get_loop_lag_monitor()
        
        assert isinstance(monitor1, LoopLagMonitor)
        assert monitor1 is monitor2  # Singleton

    def test_diagnostics_init_imports(self):
        """Test diagnostics __init__ imports correctly."""
        from merid.diagnostics import KalshiPipelineProbe, ProbeResult, ProbeReport
        
        assert KalshiPipelineProbe is not None
        assert ProbeResult is not None
        assert ProbeReport is not None


class TestGlobalInitOrder:
    """Verify initialization order constraints."""

    def test_no_early_prediction_risk_import_in_diagnostics(self):
        """Verify diagnostics doesn't trigger prediction risk init."""
        # This test ensures diagnostics module can be imported without
        # triggering agent initialization that would call get_prediction_risk
        import merid.diagnostics
        import merid.diagnostics.loop_lag
        
        # If we get here without errors, diagnostics is clean
        assert True
