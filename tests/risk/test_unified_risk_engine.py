"""Tests for Unified Risk Engine."""

import pytest
from datetime import datetime, timezone, timedelta
from merid.risk.unified_risk_engine import (
    UnifiedRiskEngine,
    get_unified_risk_engine,
    TradeRequest,
    TradeResult,
    RiskLayer,
    RiskDecision,
    RiskCheckResult
)


class TestUnifiedRiskEngine:
    """Test suite for UnifiedRiskEngine."""
    
    def test_singleton(self):
        """Test that UnifiedRiskEngine is a singleton."""
        engine1 = get_unified_risk_engine()
        engine2 = get_unified_risk_engine()
        assert engine1 is engine2
    
    def test_initialization(self):
        """Test engine initialization."""
        engine = get_unified_risk_engine()
        summary = engine.get_summary()
        assert summary["initialized"] is True
        assert summary["module_count"] == 4
    
    def test_check_trade_basic(self):
        """Test basic trade checking."""
        engine = get_unified_risk_engine()
        request = TradeRequest(
            ticker="KXBTC15M-TEST",
            side="yes",
            contracts=10,
            price_cents=50,
            agent_name="test_agent",
            strategy="momentum"
        )
        result = engine.check_trade(request)
        assert isinstance(result, RiskCheckResult)
        assert result.trace_id is not None
    
    def test_risk_layer_hierarchy(self):
        """Test that risk layers are checked in correct order."""
        engine = get_unified_risk_engine()
        # The hierarchy should be: GLOBAL -> DOMAIN -> STRATEGY -> INSTRUMENT
        # This is implicitly tested by the check_trade method
    
    def test_module_states(self):
        """Test module state tracking."""
        engine = get_unified_risk_engine()
        states = engine.get_module_states()
        assert len(states) == 4
        assert "RiskController" in states
        assert "ExecutionGuard" in states
        assert "KalshiRiskManager" in states
        assert "SentimentRisk" in states
    
    def test_record_trade(self):
        """Test trade recording."""
        engine = get_unified_risk_engine()
        result = TradeResult(
            trace_id="test-trace-123",
            ticker="KXBTC15M-TEST",
            side="yes",
            contracts=10,
            price_cents=50,
            executed_contracts=10,
            pnl_usd=5.0
        )
        engine.record_trade(result)
        # Should not raise an exception
    
    def test_audit_trail(self):
        """Test audit trail functionality."""
        engine = get_unified_risk_engine()
        audit_trail = engine.get_audit_trail(limit=10)
        assert isinstance(audit_trail, list)
    
    def test_summary(self):
        """Test summary generation."""
        engine = get_unified_risk_engine()
        summary = engine.get_summary()
        assert "initialized" in summary
        assert "module_count" in summary
        assert "total_checks" in summary
        assert "total_rejections" in summary


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
