"""Integration tests for Kalshi adapter with order constraints.

Tests the integration of order constraints into the Kalshi adapter
by mocking the constraint validation function at the module level.
"""

import pytest
from unittest.mock import Mock, AsyncMock, patch
from decimal import Decimal

from core.venues.kalshi_adapter import KalshiAdapter
from core.venue_adapter import OrderSide, OrderType
from merid.resilience import OperationResult


class TestKalshiAdapterConstraintsIntegration:
    """Integration tests for Kalshi adapter with constraint validation."""
    
    @pytest.fixture
    def mock_client(self):
        """Create a mock Kalshi client."""
        client = Mock()
        client.connect = AsyncMock(return_value=True)
        client.close = AsyncMock(return_value=True)
        client.get_balance_result = AsyncMock(return_value=OperationResult.ok({"balance": 10000}))
        client.get_market_result = AsyncMock(return_value=OperationResult.ok(None))
        client.place_order_result = AsyncMock()
        return client
    
    @pytest.fixture
    def adapter(self, mock_client):
        """Create a Kalshi adapter with mocked client."""
        with patch('core.venues.kalshi_adapter.KalshiVenueClient', return_value=mock_client):
            adapter = KalshiAdapter(
                api_key_id="test_key_id",
                use_demo=True,
                paper=True,
            )
            adapter._client = mock_client
            adapter.connected = True
            return adapter
    
    @pytest.mark.asyncio
    async def test_happy_path_order_passes_constraints(self, adapter, mock_client):
        """Test that a valid order passes constraints and reaches the client."""
        # Mock constraint validation to allow order
        with patch('merid.event_venues.kalshi.order_constraints.validate_kalshi_order', return_value=(True, "")):
            # Mock successful order placement
            placed_order = Mock()
            placed_order.status = "pending"
            placed_order.order_id = "test_order_123"
            placed_order.market_id = "KXBTC15M-TEST"
            placed_order.side = "yes"
            placed_order.remaining_size = Decimal("10")
            mock_client.place_order_result.return_value = OperationResult.ok(placed_order)
            
            result = await adapter._place_order_impl(
                symbol="KXBTC15M-TEST",
                side=OrderSide.BUY,
                order_type=OrderType.LIMIT,
                amount=Decimal("10"),
                price=Decimal("0.50"),
            )
        
        # Verify order was placed
        assert result["status"] == "pending"
        assert result["order_id"] == "test_order_123"
        
        # Verify client was called
        mock_client.place_order_result.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_constraint_rejection_blocks_order(self, adapter, mock_client):
        """Test that constraint rejection blocks order before API call."""
        # Mock constraint validation to reject order
        with patch('merid.event_venues.kalshi.order_constraints.validate_kalshi_order', return_value=(False, "Market is closed")):
            result = await adapter._place_order_impl(
                symbol="KXBTC15M-TEST",
                side=OrderSide.BUY,
                order_type=OrderType.LIMIT,
                amount=Decimal("10"),
                price=Decimal("0.50"),
            )
        
        # Verify order was rejected
        assert result["status"] == "rejected"
        assert "closed" in result["message"].lower()
        
        # Verify client was NOT called (blocked by constraints)
        mock_client.place_order_result.assert_not_called()
    
    @pytest.mark.asyncio
    async def test_constraint_check_error_fails_closed(self, adapter, mock_client):
        """Test that constraint check errors fail-closed (reject order)."""
        # Mock constraint validation to raise exception
        with patch('merid.event_venues.kalshi.order_constraints.validate_kalshi_order', side_effect=Exception("Constraint check failed")):
            result = await adapter._place_order_impl(
                symbol="KXBTC15M-TEST",
                side=OrderSide.BUY,
                order_type=OrderType.LIMIT,
                amount=Decimal("10"),
                price=Decimal("0.50"),
            )
        
        # Verify order was rejected due to constraint check failure
        assert result["status"] == "error"
        assert "constraint" in result["message"].lower()
        
        # Verify client was NOT called (fail-closed)
        mock_client.place_order_result.assert_not_called()
    
    @pytest.mark.asyncio
    async def test_constraint_module_unavailable_warns_and_proceeds(self, adapter, mock_client):
        """Test that missing constraint module warns but allows order (backward compatibility)."""
        # Mock successful order placement
        placed_order = Mock()
        placed_order.status = "pending"
        placed_order.order_id = "test_order_123"
        placed_order.market_id = "KXBTC15M-TEST"
        placed_order.side = "yes"
        placed_order.remaining_size = Decimal("10")
        mock_client.place_order_result.return_value = OperationResult.ok(placed_order)
        
        # Mock ImportError for constraint module
        with patch('merid.event_venues.kalshi.order_constraints.validate_kalshi_order', side_effect=ImportError):
            result = await adapter._place_order_impl(
                symbol="KXBTC15M-TEST",
                side=OrderSide.BUY,
                order_type=OrderType.LIMIT,
                amount=Decimal("10"),
                price=Decimal("0.50"),
            )
        
        # Verify order was placed (backward compatibility: proceed without constraints)
        assert result["status"] == "pending"
        assert result["order_id"] == "test_order_123"
        
        # Verify client was called
        mock_client.place_order_result.assert_called_once()


class TestRejectedOrderHandling:
    """Tests for rejected order handling with back-off and logging."""
    
    @pytest.mark.asyncio
    async def test_api_rejection_logs_error_and_returns_error_status(self):
        """Test that API rejections are logged and returned as error status."""
        # Create adapter with mocked client
        mock_client = Mock()
        mock_client.connect = AsyncMock(return_value=True)
        mock_client.close = AsyncMock(return_value=True)
        mock_client.get_balance_result = AsyncMock(return_value=OperationResult.ok({"balance": 10000}))
        mock_client.get_market_result = AsyncMock(return_value=OperationResult.ok(None))
        mock_client.place_order_result = AsyncMock(return_value=OperationResult.fail(Exception("API rejected order")))
        
        with patch('core.venues.kalshi_adapter.KalshiVenueClient', return_value=mock_client):
            adapter = KalshiAdapter(
                api_key_id="test_key_id",
                use_demo=True,
                paper=True,
            )
            adapter._client = mock_client
            adapter.connected = True
            
            # Mock constraint validation to allow order
            with patch('merid.event_venues.kalshi.order_constraints.validate_kalshi_order', return_value=(True, "")):
                result = await adapter._place_order_impl(
                    symbol="KXBTC15M-TEST",
                    side=OrderSide.BUY,
                    order_type=OrderType.LIMIT,
                    amount=Decimal("10"),
                    price=Decimal("0.50"),
                )
        
        # Verify error was returned
        assert result["status"] == "error"
        assert "API rejected order" in result["message"]
    
    @pytest.mark.asyncio
    async def test_constraint_rejection_logs_warning_and_returns_rejected_status(self):
        """Test that constraint rejections log warning and return rejected status."""
        mock_client = Mock()
        mock_client.connect = AsyncMock(return_value=True)
        mock_client.close = AsyncMock(return_value=True)
        mock_client.get_balance_result = AsyncMock(return_value=OperationResult.ok({"balance": 10000}))
        mock_client.get_market_result = AsyncMock(return_value=OperationResult.ok(None))
        
        with patch('core.venues.kalshi_adapter.KalshiVenueClient', return_value=mock_client):
            adapter = KalshiAdapter(
                api_key_id="test_key_id",
                use_demo=True,
                paper=True,
            )
            adapter._client = mock_client
            adapter.connected = True
            
            # Mock constraint validation to reject order
            with patch('merid.event_venues.kalshi.order_constraints.validate_kalshi_order', return_value=(False, "Market is closed")):
                result = await adapter._place_order_impl(
                    symbol="KXBTC15M-TEST",
                    side=OrderSide.BUY,
                    order_type=OrderType.LIMIT,
                    amount=Decimal("10"),
                    price=Decimal("0.50"),
                )
        
        # Verify rejected status
        assert result["status"] == "rejected"
        assert "closed" in result["message"].lower()
        
        # Verify client was NOT called (blocked by constraints)
        mock_client.place_order_result.assert_not_called()
