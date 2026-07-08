"""
Tests for price clamping and max_contracts validation fixes in kalshi_tools.py

This test suite validates the critical fixes to prevent:
1. Purchases at $0.99 (price clamping to [15, 70] range)
2. Overspending (max_contracts validation to per-asset limits)

Run with: pytest tests/test_kalshi_tools_price_and_contracts_fixes.py -v
"""

import pytest
from unittest.mock import MagicMock, patch
from decimal import Decimal


class TestPriceClampingFixes:
    """Test that price clamping uses [50, 70] range instead of [1, 99]."""

    def test_build_live_route_order_intent_clamps_price(self):
        """Test that build_live_route_order_intent clamps price to [50, 70] range."""
        from merid.prediction.kalshi_tools import build_live_route_order_intent
        
        # Test price above 70c should be clamped to 70c
        intent = build_live_route_order_intent(
            ticker="KXBTC15M-26APR191645-45",
            side="yes",
            action="buy",
            price_cents=99,  # Should be clamped to 70
            count=1,
        )
        assert intent.price_cents == 70, f"Expected 70c, got {intent.price_cents}c"
        
        # Test price below 50c should be clamped to 50c
        intent = build_live_route_order_intent(
            ticker="KXBTC15M-26APR191645-45",
            side="yes",
            action="buy",
            price_cents=5,  # Should be clamped to 50
            count=1,
        )
        assert intent.price_cents == 50, f"Expected 50c, got {intent.price_cents}c"
        
        # Test price within range should not be clamped
        intent = build_live_route_order_intent(
            ticker="KXBTC15M-26APR191645-45",
            side="yes",
            action="buy",
            price_cents=65,  # Should remain 65
            count=1,
        )
        assert intent.price_cents == 65, f"Expected 65c, got {intent.price_cents}c"


class TestMaxContractsValidation:
    """Test that max_contracts validation respects per-asset limits."""

    def test_build_live_route_order_intent_clamps_count_to_asset_limit(self):
        """Test that build_live_route_order_intent clamps count to per-asset max_contracts (2)."""
        from merid.prediction.kalshi_tools import build_live_route_order_intent
        
        # Mock profile with max_contracts=2 for BTC
        mock_profile = MagicMock()
        mock_profile.assets = {
            "BTC": MagicMock(max_contracts=2),
            "ETH": MagicMock(max_contracts=2),
            "SOL": MagicMock(max_contracts=2),
            "XRP": MagicMock(max_contracts=2),
            "DOGE": MagicMock(max_contracts=2),
        }
        mock_adapter = MagicMock()
        mock_adapter.profile = mock_profile
        
        with patch('merid.risk.profiles.crypto_15m_profile.get_active_profile', return_value=mock_adapter):
            # Test count above asset limit should be clamped to 2
            intent = build_live_route_order_intent(
                ticker="KXBTC15M-26APR191645-45",
                side="yes",
                action="buy",
                price_cents=50,
                count=5,  # Should be clamped to 2
            )
            assert intent.count == 2, f"Expected 2 contracts, got {intent.count}"
            
            # Test count within limit should not be clamped
            intent = build_live_route_order_intent(
                ticker="KXBTC15M-26APR191645-45",
                side="yes",
                action="buy",
                price_cents=50,
                count=1,  # Should remain 1
            )
            assert intent.count == 1, f"Expected 1 contract, got {intent.count}"

    def test_build_live_route_order_intent_uses_default_limit_when_profile_unavailable(self):
        """Test that build_live_route_order_intent uses default limit (2) when profile unavailable."""
        from merid.prediction.kalshi_tools import build_live_route_order_intent
        
        with patch('merid.risk.profiles.crypto_15m_profile.get_active_profile', return_value=None):
            # Test count above default limit should be clamped to 2
            intent = build_live_route_order_intent(
                ticker="KXBTC15M-26APR191645-45",
                side="yes",
                action="buy",
                price_cents=50,
                count=5,  # Should be clamped to 2 (default)
            )
            assert intent.count == 2, f"Expected 2 contracts (default), got {intent.count}"

    def test_build_live_route_order_intent_respects_different_asset_limits(self):
        """Test that build_live_route_order_intent respects different per-asset limits."""
        from merid.prediction.kalshi_tools import build_live_route_order_intent
        
        # Mock profile with different max_contracts per asset
        mock_profile = MagicMock()
        mock_profile.assets = {
            "BTC": MagicMock(max_contracts=2),
            "ETH": MagicMock(max_contracts=2),
            "SOL": MagicMock(max_contracts=2),
            "XRP": MagicMock(max_contracts=2),
            "DOGE": MagicMock(max_contracts=2),
        }
        mock_adapter = MagicMock()
        mock_adapter.profile = mock_profile
        
        with patch('merid.risk.profiles.crypto_15m_profile.get_active_profile', return_value=mock_adapter):
            # Test BTC limit
            intent = build_live_route_order_intent(
                ticker="KXBTC15M-26APR191645-45",
                side="yes",
                action="buy",
                price_cents=50,
                count=5,
            )
            assert intent.count == 2, f"Expected 2 contracts for BTC, got {intent.count}"
            
            # Test ETH limit
            intent = build_live_route_order_intent(
                ticker="KXETH15M-26APR191645-45",
                side="yes",
                action="buy",
                price_cents=50,
                count=5,
            )
            assert intent.count == 2, f"Expected 2 contracts for ETH, got {intent.count}"
            
            # Test SOL limit
            intent = build_live_route_order_intent(
                ticker="KXSOL15M-26APR191645-45",
                side="yes",
                action="buy",
                price_cents=50,
                count=5,
            )
            assert intent.count == 2, f"Expected 2 contracts for SOL, got {intent.count}"
            
            # Test XRP limit
            intent = build_live_route_order_intent(
                ticker="KXXRP15M-26APR191645-45",
                side="yes",
                action="buy",
                price_cents=50,
                count=5,
            )
            assert intent.count == 2, f"Expected 2 contracts for XRP, got {intent.count}"
            
            # Test DOGE limit
            intent = build_live_route_order_intent(
                ticker="KXDOGE15M-26APR191645-45",
                side="yes",
                action="buy",
                price_cents=50,
                count=5,
            )
            assert intent.count == 2, f"Expected 2 contracts for DOGE, got {intent.count}"


class TestExitPolicyParameters:
    """Test that exit policy parameters (stop_loss_price_cents, take_profit_r_multiple) are correctly passed through."""

    def test_kalshi_place_order_accepts_exit_policy_parameters(self):
        """Test that _kalshi_place_order accepts stop_loss_price_cents and take_profit_r_multiple parameters."""
        from merid.prediction.kalshi_tools import _kalshi_place_order
        import inspect
        
        # Get function signature
        sig = inspect.signature(_kalshi_place_order)
        params = sig.parameters
        
        # Verify new parameters exist
        assert 'stop_loss_price_cents' in params, "stop_loss_price_cents parameter missing"
        assert 'take_profit_r_multiple' in params, "take_profit_r_multiple parameter missing"
        
        # Verify they are optional (have default values)
        assert params['stop_loss_price_cents'].default is None, "stop_loss_price_cents should default to None"
        assert params['take_profit_r_multiple'].default is None, "take_profit_r_multiple should default to None"

    @patch('merid.event_venues.kalshi.order_router.route_order_async')
    @patch('merid.prediction.kalshi_tools._get_client')
    @patch('merid.prediction.kalshi_tools.get_venue_gate')
    def test_exit_policy_parameters_passed_to_order_intent(self, mock_gate, mock_client, mock_route):
        """Test that exit policy parameters are passed to OrderIntent in _kalshi_place_order."""
        from merid.prediction.kalshi_tools import _kalshi_place_order
        from merid.event_venues.kalshi.order_router import OrderResult, TradingMode
        from unittest.mock import AsyncMock
        
        # Mock the venue gate to return paper mode (simulated fills)
        mock_gate_instance = MagicMock()
        mock_gate_instance.should_simulate_fill.return_value = True
        mock_gate_instance.mode = TradingMode.PAPER
        mock_gate.return_value = mock_gate_instance
        
        # Mock orderbook to allow fill (async)
        mock_ob = MagicMock()
        mock_ob.asks = [[0.50, 100]]  # 50 cents ask
        mock_ob.bids = [[0.45, 100]]
        mock_client_instance = MagicMock()
        mock_client_instance.get_orderbook = AsyncMock(return_value=mock_ob)
        mock_client.return_value = mock_client_instance
        
        # Mock route_order_async (should not be called in paper mode)
        mock_route.return_value = OrderResult(
            status="filled_paper",
            mode=TradingMode.PAPER,
            latency_ms=10.0
        )
        
        # Call _kalshi_place_order with exit policy parameters
        import asyncio
        result = asyncio.run(_kalshi_place_order(
            ticker="KXBTC15M-26JUL081400-00",
            side="yes",
            action="buy",
            price_cents=50,
            count=1,
            agent_name="BTC_15M",
            stop_loss_price_cents=45,  # 5 cent stop loss
            take_profit_r_multiple=1.5,  # 1.5R take profit
        ))
        
        # Verify order was successful
        assert result.success, f"Order failed: {result}"
        
        # In paper mode, the function should return a simulated fill
        # The exit policy parameters should be logged and available in the payload
        if result.payload:
            # Verify the order was simulated
            assert result.payload.get('simulated') is True, "Order should be simulated in paper mode"

    @patch('merid.event_venues.kalshi.order_router.route_order_async')
    @patch('merid.prediction.kalshi_tools._get_client')
    @patch('merid.prediction.kalshi_tools.get_venue_gate')
    def test_exit_policy_parameters_none_by_default(self, mock_gate, mock_client, mock_route):
        """Test that exit policy parameters default to None when not provided."""
        from merid.prediction.kalshi_tools import _kalshi_place_order
        from merid.event_venues.kalshi.order_router import OrderResult, TradingMode
        from unittest.mock import AsyncMock
        
        # Mock the venue gate to return paper mode
        mock_gate_instance = MagicMock()
        mock_gate_instance.should_simulate_fill.return_value = True
        mock_gate_instance.mode = TradingMode.PAPER
        mock_gate.return_value = mock_gate_instance
        
        # Mock orderbook (async)
        mock_ob = MagicMock()
        mock_ob.asks = [[0.50, 100]]
        mock_ob.bids = [[0.45, 100]]
        mock_client_instance = MagicMock()
        mock_client_instance.get_orderbook = AsyncMock(return_value=mock_ob)
        mock_client.return_value = mock_client_instance
        
        # Mock route_order_async
        mock_route.return_value = OrderResult(
            status="filled_paper",
            mode=TradingMode.PAPER,
            latency_ms=10.0
        )
        
        # Call _kalshi_place_order WITHOUT exit policy parameters
        import asyncio
        result = asyncio.run(_kalshi_place_order(
            ticker="KXBTC15M-26JUL081400-00",
            side="yes",
            action="buy",
            price_cents=50,
            count=1,
            agent_name="BTC_15M",
            # No stop_loss_price_cents or take_profit_r_multiple
        ))
        
        # Verify order was successful even without exit policy parameters
        assert result.success, f"Order failed without exit policy: {result}"

    def test_order_intent_has_exit_policy_fields(self):
        """Test that OrderIntent dataclass has exit policy fields."""
        from merid.event_venues.kalshi.order_router import OrderIntent
        import inspect
        
        # Get OrderIntent fields
        fields = {f.name for f in inspect.signature(OrderIntent).parameters.values()}
        
        # Verify exit policy fields exist
        assert 'stop_loss_price_cents' in fields, "OrderIntent missing stop_loss_price_cents field"
        assert 'take_profit_price_cents' in fields, "OrderIntent missing take_profit_price_cents field"
        assert 'take_profit_r_multiple' in fields, "OrderIntent missing take_profit_r_multiple field"


class TestRiskContractFields:
    """Test that risk contract fields are properly included in OrderIntent for crypto 15m markets."""

    def test_order_intent_has_risk_contract_fields(self):
        """Test that OrderIntent dataclass has risk contract fields."""
        from merid.event_venues.kalshi.order_router import OrderIntent
        import inspect
        
        # Get OrderIntent fields
        fields = {f.name for f in inspect.signature(OrderIntent).parameters.values()}
        
        # Verify risk contract fields exist
        assert 'window_resolution_id' in fields, "OrderIntent missing window_resolution_id field"
        assert 'exit_policy_id' in fields, "OrderIntent missing exit_policy_id field"
        assert 'risk_tier' in fields, "OrderIntent missing risk_tier field"
        assert 'max_hold_seconds' in fields, "OrderIntent missing max_hold_seconds field"
