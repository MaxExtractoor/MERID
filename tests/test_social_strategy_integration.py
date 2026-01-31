"""
Tests for Phase 21c: Social-Aware Quant Integration

Validates that social strategies are properly gated by:
- Social risk limits (exposure caps, correlation, drawdown)
- Data freshness requirements
- Market confirmation checks
- Kill switch enforcement
"""

import pytest
import time
from unittest.mock import Mock, patch

from social.social_aware_quant import (
    SocialAwareQuantEngine,
    SocialRiskLimits,
    SocialSource,
    get_social_aware_quant_engine,
)
from core.social_strategy_router import evaluate_social_trade, release_social_position
from core.strategy_versioning import (
    StrategyVersion,
    VersionStatus,
    get_version_registry,
)
from governance.multi_agent_risk_controls import get_multi_agent_risk_controls


class TestSocialStrategyGating:
    """Test social strategy gating and risk enforcement."""
    
    def setup_method(self):
        """Reset state before each test."""
        engine = get_social_aware_quant_engine()
        engine.reset_state()
    
    def _register_social_strategy(self, strategy_id: str, asset: str) -> None:
        registry = get_version_registry()
        strategy = StrategyVersion(
            strategy_id=strategy_id,
            version="1.0.0",
            status=VersionStatus.PRODUCTION,
            created_at=time.time(),
            promoted_at=time.time(),
            deprecated_at=None,
            performance_metrics={},
            config={},
            dependencies=[],
            changelog="Test social strategy",
            is_social_strategy=True,
            social_assets=[asset],
        )
        registry.register_version(strategy)
        registry.set_active_version(strategy.strategy_id, strategy.version)

    def test_social_trade_evaluation_success(self):
        """Test successful social trade evaluation."""
        engine = get_social_aware_quant_engine()
        engine.register_social_asset("BTC")
        
        # Create mock strategy
        self._register_social_strategy("social_btc_v1", "BTC")
        engine.ingest_social_signal(
            source=SocialSource.TWITTER,
            asset="BTC",
            sentiment_score=0.75,
            volume=500,
            velocity=1.2,
            influencer_mentions=3,
            whale_mentions=1,
        )
        engine.check_market_confirmation(
            asset="BTC",
            price_change_1h=0.03,
            price_change_24h=0.08,
            volume_24h=5_000_000.0,
            liquidity_depth=10_000_000.0,
            spread_bps=5.0,
            volatility_24h=0.1,
            sentiment_direction=0.75,
        )
        
        # Evaluate trade
        result = evaluate_social_trade(
            strategy_id="social_btc_v1",
            asset="BTC",
            portfolio_value=100000.0,
            sentiment_score=0.7,
            market_metrics={"price": 50000.0, "volume_24h": 1000000.0},
        )
        
        # Should be allowed with proper sizing
        assert result["allowed"] is True
        assert "sizing" in result
        assert result["sizing"]["size_usd"] > 0
    
    def test_social_trade_blocked_by_stale_data(self):
        """Test that stale social data blocks trades."""
        engine = get_social_aware_quant_engine()
        engine.register_social_asset("DOGE")
        self._register_social_strategy("social_doge_v1", "DOGE")
        
        # Don't ingest any signals - data will be stale
        result = evaluate_social_trade(
            strategy_id="social_doge_v1",
            asset="DOGE",
            portfolio_value=100000.0,
            sentiment_score=0.8,
            market_metrics={"price": 0.10},
        )
        
        # Should be blocked due to stale data
        assert result["allowed"] is False
        assert any("stale" in reason.lower() or "fresh" in reason.lower() for reason in result["reasons"])
    
    def test_social_trade_blocked_by_kill_switch(self):
        """Test that kill switch blocks all social trades."""
        engine = get_social_aware_quant_engine()
        engine.register_social_asset("ETH")
        engine.activate_kill_switch("Social drawdown exceeded")
        self._register_social_strategy("social_eth_v1", "ETH")
        
        result = evaluate_social_trade(
            strategy_id="social_eth_v1",
            asset="ETH",
            portfolio_value=100000.0,
            sentiment_score=0.6,
            market_metrics={"price": 3000.0},
        )
        
        # Should be blocked by kill switch
        assert result["allowed"] is False
        assert any("kill switch" in reason.lower() for reason in result["reasons"])
    
    def test_social_trade_blocked_by_exposure_cap(self):
        """Test that exposure caps are enforced."""
        engine = get_social_aware_quant_engine()
        engine.register_social_asset("SOL")
        self._register_social_strategy("social_sol_v1", "SOL")
        
        # Register large existing allocation to hit cap
        engine.register_position_allocation("SOL", 9000.0)  # 9% of 100k portfolio
        
        result = evaluate_social_trade(
            strategy_id="social_sol_v1",
            asset="SOL",
            portfolio_value=100000.0,
            sentiment_score=0.9,
            market_metrics={"price": 100.0},
        )
        
        # Should be blocked or heavily constrained
        if result["allowed"]:
            # If allowed, size should be very small
            assert result["sizing"]["size_usd"] < 1500.0  # Can't exceed 10% total
        else:
            assert any("exposure" in reason.lower() for reason in result["reasons"])
    
    def test_social_position_release(self):
        """Test that closing positions releases tracked exposure."""
        engine = get_social_aware_quant_engine()
        engine.register_social_asset("ADA")
        
        # Allocate position
        engine.register_position_allocation("ADA", 5000.0)
        
        # Check exposure is tracked
        constraints = engine.get_position_constraints("ADA")
        assert constraints["asset_exposure"] == 5000.0
        
        # Release position
        release_social_position("ADA", 5000.0)
        
        # Check exposure is released
        constraints_after = engine.get_position_constraints("ADA")
        assert constraints_after["asset_exposure"] == 0.0
    
    def test_multi_agent_risk_controls_social_validation(self):
        """Test multi-agent risk controls validate social constraints."""
        risk_controls = get_multi_agent_risk_controls()
        engine = get_social_aware_quant_engine()
        engine.register_social_asset("AVAX")
        engine.activate_kill_switch("Test kill switch")
        
        strategy = StrategyVersion(
            strategy_id="social_avax_v1",
            version="1.0.0",
            status=VersionStatus.PRODUCTION,
            created_at=time.time(),
            promoted_at=None,
            deprecated_at=None,
            performance_metrics={},
            config={},
            dependencies=[],
            changelog="Test",
            is_social_strategy=True,
            social_assets=["AVAX"],
        )
        
        sizing_result = {
            "allowed": True,
            "size_usd": 1000.0,
            "constraints": {
                "kill_switch_active": True,
                "kill_switch_reason": "Test kill switch",
                "data_fresh": True,
                "confirmation_available": True,
                "asset_exposure": 0.0,
            },
            "portfolio_value": 100000.0,
            "remaining_social_budget": 9000.0,
        }
        
        approved, violations = risk_controls.validate_social_constraints(
            strategy=strategy,
            sizing_result=sizing_result,
        )
        
        # Should be rejected due to kill switch
        assert approved is False
        assert any("kill switch" in v.lower() for v in violations)
    
    def test_social_trade_history_tracking(self):
        """Test that social trades are tracked in risk controls."""
        risk_controls = get_multi_agent_risk_controls()
        
        risk_controls.register_social_trade(
            agent_id="strategy_agent",
            strategy_id="social_test_v1",
            asset="BTC",
            size_usd=5000.0,
            metadata={"sentiment_score": 0.75},
        )
        
        # Verify trade is in history
        assert len(risk_controls._social_trade_history) > 0
        last_trade = risk_controls._social_trade_history[-1]
        assert last_trade["asset"] == "BTC"
        assert last_trade["size_usd"] == 5000.0


class TestSocialStrategyVersioning:
    """Test strategy versioning integration with social assets."""
    
    def test_social_strategy_registration(self):
        """Test that social assets are registered on strategy promotion."""
        from core.strategy_versioning import get_version_registry
        
        registry = get_version_registry()
        engine = get_social_aware_quant_engine()
        
        # Create social strategy
        strategy = StrategyVersion(
            strategy_id="social_link_v1",
            version="1.0.0",
            status=VersionStatus.DEVELOPMENT,
            created_at=time.time(),
            promoted_at=None,
            deprecated_at=None,
            performance_metrics={},
            config={},
            dependencies=[],
            changelog="Social strategy for LINK",
            is_social_strategy=True,
            social_assets=["LINK"],
        )
        
        # Register strategy
        registry.register_version(strategy)
        
        # Verify LINK is registered as social asset
        assert engine.is_social_asset("LINK")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
