"""Tests for YES/NO Sum Arbitrage Execution.

Tests the profitability enhancement that executes arbitrage when YES+NO < 100c.

Arbitrage is now enabled via YAML profile configuration (kalshi_crypto_15m_v2.yaml).
Tests verify the end-to-end wiring from YAML config → duality validator → callback → execution.
"""

import pytest
import os
from unittest.mock import Mock, patch, AsyncMock
from pathlib import Path
import yaml

from merid.event_venues.kalshi import duality_validator
from merid.event_venues.kalshi.duality_validator import (
    DualityValidator,
    DualityCheckResult,
    ArbitrageOpportunity,
    get_duality_validator,
)


class TestArbitrageConfigLoading:
    """Test arbitrage configuration loading from YAML profile."""
    
    def test_yaml_config_loading(self):
        """Test that arbitrage config is loaded from YAML profile."""
        # The config should be loaded from kalshi_crypto_15m_v2.yaml
        # Check that the module-level constants are set correctly
        assert hasattr(duality_validator, 'ARBITRAGE_ENABLED')
        assert hasattr(duality_validator, 'ARBITRAGE_THRESHOLD_CENTS')
        assert hasattr(duality_validator, 'ARBITRAGE_MAX_SIZE_CONTRACTS')
        assert hasattr(duality_validator, 'ARBITRAGE_EXECUTION_TIMEOUT_MS')
    
    def test_yaml_config_values(self):
        """Test that YAML config values match expected values."""
        # Read the YAML file directly to verify
        profile_path = Path(__file__).parent.parent.parent.parent / "config" / "profiles" / "kalshi_crypto_15m_v2.yaml"
        if profile_path.exists():
            with open(profile_path, 'r', encoding='utf-8') as f:
                profile_config = yaml.safe_load(f)
                if profile_config and 'yes_no_arbitrage' in profile_config:
                    arb_config = profile_config['yes_no_arbitrage']
                    # The module should have loaded these values
                    # Note: These may be overridden by env var in tests
                    assert arb_config.get('pair_cost_threshold_cents') == 95
                    assert arb_config.get('max_size_contracts') == 10
                    assert arb_config.get('execution_timeout_ms') == 500
    
    def test_env_var_override(self):
        """Test that environment variable overrides YAML config."""
        # When env var is set, it should override YAML
        with patch.dict(os.environ, {"MERID_YES_NO_ARBITRAGE_ENABLED": "true"}):
            # Reload the config function
            from merid.event_venues.kalshi.duality_validator import _load_arbitrage_config
            config = _load_arbitrage_config()
            assert config['enabled'] is True


class TestArbitrageDetection:
    """Test arbitrage opportunity detection in duality validator."""
    
    def test_arbitrage_opportunity_detected_when_enabled(self):
        """Test that arbitrage is detected when YES_ask + NO_bid < threshold and feature is enabled."""
        validator = DualityValidator()
        
        # Enable arbitrage for this test
        with patch.object(duality_validator, 'ARBITRAGE_ENABLED', True):
            # For arbitrage: yes_ask + no_bid < threshold (95c from YAML)
            # For valid duality: yes_bid + no_ask = 100c (first check must pass)
            # Arbitrage check happens before NO_bid + YES_ask duality check
            # 
            # Try: yes_ask=47, yes_bid=53, no_ask=47, no_bid=47
            # Check:
            # - yes_bid + no_ask = 53 + 47 = 100 ✓ (first duality check passes)
            # - yes_ask + no_bid = 47 + 47 = 94 < 95 ✓ (arbitrage triggers before second duality check)
            result = validator.check_yes_no_duality(
                yes_bid=53,
                no_bid=47,
                yes_ask=47,
                no_ask=47,
                ticker="KXBTCD-25JUN-T100000"
            )
            
            # Should be valid (not a violation) but have arbitrage opportunity
            assert result.is_valid is True
            assert result.arbitrage_opportunity is not None
            assert result.arbitrage_opportunity.edge_cents == 6  # 100 - (47 + 47)
            assert result.arbitrage_opportunity.yes_ask == 47
            assert result.arbitrage_opportunity.no_bid == 47
            # Check that tickers are derived from market_id
            assert result.arbitrage_opportunity.yes_ticker == "KXBTCD-25JUN-T100000-YES"
            assert result.arbitrage_opportunity.no_ticker == "KXBTCD-25JUN-T100000-NO"
            assert result.arbitrage_opportunity.market_id == "KXBTCD-25JUN-T100000"
    
    def test_arbitrage_not_detected_when_disabled(self):
        """Test that arbitrage is not detected when feature is disabled."""
        validator = DualityValidator()
        
        # Ensure arbitrage is disabled
        with patch.object(duality_validator, 'ARBITRAGE_ENABLED', False):
            # Provide valid duality data to pass duality checks
            # yes_bid + no_ask = 48 + 52 = 100 ✓
            # no_bid + yes_ask = 52 + 48 = 100 ✓
            # Not crossed: yes_bid(48) < no_ask(52) ✓, no_bid(52) < yes_ask(48) ✗ (crossed!)
            # Fix: use yes_bid=48, no_ask=52, no_bid=48, yes_ask=52
            result = validator.check_yes_no_duality(
                yes_bid=48,
                no_bid=48,
                yes_ask=52,
                no_ask=52,
                ticker="KXBTCD-25JUN-T100000"
            )
            
            # Should be valid but no arbitrage opportunity
            assert result.is_valid is True
            assert result.arbitrage_opportunity is None
    
    def test_arbitrage_below_threshold(self):
        """Test that arbitrage below threshold is not executed."""
        validator = DualityValidator()
        
        with patch.object(duality_validator, 'ARBITRAGE_ENABLED', True):
            with patch.object(duality_validator, 'ARBITRAGE_THRESHOLD_CENTS', 95):
                # Provide valid duality data
                # yes_bid + no_ask = 48 + 52 = 100 ✓
                # no_bid + yes_ask = 48 + 52 = 100 ✓
                # YES + NO = 48 + 52 = 100c, which is >= 95c threshold, so no arbitrage
                result = validator.check_yes_no_duality(
                    yes_bid=48,
                    no_bid=48,
                    yes_ask=52,
                    no_ask=52,
                    ticker="KXBTCD-25JUN-T100000"
                )
                
                # Should be valid but no arbitrage opportunity (at or above threshold)
                assert result.is_valid is True
                assert result.arbitrage_opportunity is None
    
    def test_arbitrage_recommended_size(self):
        """Test that recommended size is calculated correctly."""
        validator = DualityValidator()
        
        with patch.object(duality_validator, 'ARBITRAGE_ENABLED', True):
            with patch.object(duality_validator, 'ARBITRAGE_MAX_SIZE_CONTRACTS', 10):
                # Provide valid duality data with arbitrage opportunity
                # yes_bid + no_ask = 55 + 45 = 100 ✓
                # no_bid + yes_ask = 45 + 55 = 100 ✓
                # YES + NO = 45 + 45 = 90c, which is < 95c threshold, so arbitrage triggers
                # Edge = 10c, edge // 2 = 5, min(10, 5) = 5
                result = validator.check_yes_no_duality(
                    yes_bid=55,
                    no_bid=45,
                    yes_ask=45,
                    no_ask=45,
                    ticker="KXBTCD-25JUN-T100000"
                )
                
                # Recommended size should be min(max_size, edge // 2)
                assert result.arbitrage_opportunity is not None
                assert result.arbitrage_opportunity.recommended_size == 5
    
    def test_arbitrage_callback_invoked(self):
        """Test that arbitrage callback is invoked when opportunity is detected."""
        validator = DualityValidator()
        callback_mock = Mock()
        validator.set_arbitrage_callback(callback_mock)
        
        with patch.object(duality_validator, 'ARBITRAGE_ENABLED', True):
            # Provide valid duality data with arbitrage opportunity
            # yes_bid + no_ask = 55 + 45 = 100 ✓
            # no_bid + yes_ask = 45 + 55 = 100 ✓
            # YES + NO = 45 + 45 = 90c, which is < 95c threshold, so arbitrage triggers
            result = validator.check_yes_no_duality(
                yes_bid=55,
                no_bid=45,
                yes_ask=45,
                no_ask=45,
                ticker="KXBTCD-25JUN-T100000"
            )
            
            # Callback should have been invoked
            callback_mock.assert_called_once()
            assert isinstance(callback_mock.call_args[0][0], ArbitrageOpportunity)
    
    def test_arbitrage_callback_error_handling(self):
        """Test that callback errors are logged but don't crash validator."""
        validator = DualityValidator()
        
        # Callback that raises an exception
        def failing_callback(opp):
            raise ValueError("Test error")
        
        validator.set_arbitrage_callback(failing_callback)
        
        with patch.object(duality_validator, 'ARBITRAGE_ENABLED', True):
            # Provide valid duality data with arbitrage opportunity
            # yes_bid + no_ask = 55 + 45 = 100 ✓
            # no_bid + yes_ask = 45 + 55 = 100 ✓
            # YES + NO = 45 + 45 = 90c, which is < 95c threshold, so arbitrage triggers
            # Should not raise exception despite callback error
            result = validator.check_yes_no_duality(
                yes_bid=55,
                no_bid=45,
                yes_ask=45,
                no_ask=45,
                ticker="KXBTCD-25JUN-T100000"
            )
            
            # Should still return valid result with arbitrage opportunity
            assert result.is_valid is True
            assert result.arbitrage_opportunity is not None


class TestArbitrageOpportunity:
    """Test ArbitrageOpportunity dataclass."""
    
    def test_arbitrage_opportunity_creation(self):
        """Test creation of ArbitrageOpportunity with all fields."""
        opp = ArbitrageOpportunity(
            edge_cents=5,
            yes_ask=48,
            no_bid=47,
            yes_ticker="KXBTCD-25JUN-T100000-YES",
            no_ticker="KXBTCD-25JUN-T100000-NO",
            market_id="KXBTCD-25JUN-T100000",
            recommended_size=3
        )
        
        assert opp.edge_cents == 5
        assert opp.yes_ask == 48
        assert opp.no_bid == 47
        assert opp.yes_ticker == "KXBTCD-25JUN-T100000-YES"
        assert opp.no_ticker == "KXBTCD-25JUN-T100000-NO"
        assert opp.market_id == "KXBTCD-25JUN-T100000"
        assert opp.recommended_size == 3
    
    def test_arbitrage_opportunity_defaults(self):
        """Test ArbitrageOpportunity with default values."""
        opp = ArbitrageOpportunity(
            edge_cents=3,
            yes_ask=49,
            no_bid=48
        )
        
        assert opp.yes_ticker is None
        assert opp.no_ticker is None
        assert opp.market_id is None
        assert opp.recommended_size == 1  # Default


class TestArbitrageIntegration:
    """Integration tests for arbitrage with order router."""
    
    @pytest.mark.asyncio
    async def test_execute_arbitrage_async(self):
        """Test execute_arbitrage_async function."""
        from merid.event_venues.kalshi.order_router import execute_arbitrage_async, OrderResult
        
        # Mock route_order_async to return successful results
        with patch('merid.event_venues.kalshi.order_router.route_order_async') as mock_route:
            mock_route.return_value = OrderResult(
                status="filled",
                mode="live",
                reason="",
                latency_ms=100.0,
            )
            
            results = await execute_arbitrage_async(
                yes_ticker="KXBTCD-25JUN-T100000-YES",
                no_ticker="KXBTCD-25JUN-T100000-NO",
                yes_ask_cents=48,
                no_bid_cents=48,
                size=5,
                market_id="KXBTCD-25JUN-T100000"
            )
            
            # Should have called route_order_async twice (YES and NO)
            assert mock_route.call_count == 2
            
            # Should return both results
            assert "yes" in results
            assert "no" in results
            assert results["yes"].status == "filled"
            assert results["no"].status == "filled"
    
    @pytest.mark.asyncio
    async def test_execute_arbitrage_async_partial_fill(self):
        """Test execute_arbitrage_async with partial fill."""
        from merid.event_venues.kalshi.order_router import execute_arbitrage_async, OrderResult
        
        # Mock route_order_async to return mixed results
        def mock_route_side(intent):
            if intent.side == "yes":
                return OrderResult(status="filled", mode="live", reason="", latency_ms=100.0)
            else:
                return OrderResult(status="rejected", mode="live", reason="no_liquidity", latency_ms=50.0)
        
        with patch('merid.event_venues.kalshi.order_router.route_order_async', side_effect=mock_route_side):
            results = await execute_arbitrage_async(
                yes_ticker="KXBTCD-25JUN-T100000-YES",
                no_ticker="KXBTCD-25JUN-T100000-NO",
                yes_ask_cents=48,
                no_bid_cents=48,
                size=5
            )
            
            # Should return both results
            assert results["yes"].status == "filled"
            assert results["no"].status == "rejected"


class TestArbitrageCallbackWiring:
    """Test that arbitrage callback is wired in main_15m_lean.py startup."""
    
    def test_callback_registration_in_lifespan(self):
        """Test that the lifespan function registers the arbitrage callback."""
        # This test verifies that the callback wiring code exists in main_15m_lean.py
        # We can't easily test the actual execution without a full FastAPI app,
        # but we can verify the code structure
        
        import inspect
        from web.main_15m_lean import lifespan
        
        # Get the source code of the lifespan function
        source = inspect.getsource(lifespan)
        
        # Verify that the callback wiring code exists
        assert "set_arbitrage_callback" in source, "Arbitrage callback registration not found in lifespan"
        assert "arbitrage_execution_callback" in source, "Arbitrage callback function not found in lifespan"
        assert "execute_arbitrage_async" in source, "execute_arbitrage_async import not found in lifespan"
        assert "get_duality_validator" in source, "get_duality_validator import not found in lifespan"
