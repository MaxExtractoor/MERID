"""Test Kalshi business reject refund - window exposure recovery.

This test verifies that when Kalshi venue rejects orders with KalshiBusinessError,
the window exposure is properly refunded to prevent permanent capacity consumption.
"""

import pytest
from unittest.mock import Mock, patch, AsyncMock, MagicMock
from decimal import Decimal

from merid.event_venues.kalshi.venue_adapter import KalshiVenueAdapter
from merid.event_venues.kalshi import KalshiBusinessError
from merid.event_venues.base import VenueOrder


@pytest.fixture
def mock_client():
    """Mock Kalshi client."""
    client = AsyncMock()
    client.connect = AsyncMock()
    client.place_order = AsyncMock()
    return client


@pytest.fixture
def venue_adapter(mock_client):
    """Create KalshiVenueAdapter with mocked client."""
    adapter = KalshiVenueAdapter(mode="live")
    adapter._client = mock_client
    return adapter


class TestKalshiBusinessRejectRefund:
    """Test window exposure refund on Kalshi business rejects."""

    @pytest.mark.asyncio
    async def test_business_reject_refunds_window_exposure(self, venue_adapter, mock_client):
        """Test that KalshiBusinessError triggers window exposure refund."""
        # Setup: Mock KalshiBusinessError on place_order
        business_error = KalshiBusinessError(
            "Invalid ticker",
            status_code=400,
            reason_code=2
        )
        mock_client.place_order.side_effect = business_error

        # Create test order
        order = VenueOrder(
            market_id="KXBTC15M-26JUL020700-00",
            side="buy",
            size=Decimal("100"),
            price=Decimal("0.50"),
            order_type="limit",
            client_order_id="test_agent_123"
        )

        # Mock risk envelope
        mock_envelope = MagicMock()
        mock_envelope.refund_order_execution = MagicMock()

        with patch(
            'merid.risk.profiles.kalshi_crypto_15m_risk_envelope.get_kalshi_crypto_15m_risk_envelope',
            return_value=mock_envelope
        ):
            # Submit order should raise but also refund
            with pytest.raises(RuntimeError, match="Order submission failed"):
                await venue_adapter._submit_live_order(order)

        # Verify refund was called
        mock_envelope.refund_order_execution.assert_called_once()
        call_args = mock_envelope.refund_order_execution.call_args
        
        # Verify correct parameters
        assert call_args[1]['agent_id'] == "test_agent_123"
        assert call_args[1]['order_notional_usd'] == 50.0  # 100 * 0.50

    @pytest.mark.asyncio
    async def test_non_business_error_no_refund(self, venue_adapter, mock_client):
        """Test that non-business errors do not trigger refund."""
        # Setup: Mock generic exception on place_order
        generic_error = RuntimeError("Network error")
        mock_client.place_order.side_effect = generic_error

        # Create test order
        order = VenueOrder(
            market_id="KXBTC15M-26JUL020700-00",
            side="buy",
            size=Decimal("100"),
            price=Decimal("0.50"),
            order_type="limit",
            client_order_id="test_agent_123"
        )

        # Mock risk envelope
        mock_envelope = MagicMock()
        mock_envelope.refund_order_execution = MagicMock()

        with patch(
            'merid.risk.profiles.kalshi_crypto_15m_risk_envelope.get_kalshi_crypto_15m_risk_envelope',
            return_value=mock_envelope
        ):
            # Submit order should raise but NOT refund
            with pytest.raises(RuntimeError, match="Order submission failed"):
                await venue_adapter._submit_live_order(order)

        # Verify refund was NOT called
        mock_envelope.refund_order_execution.assert_not_called()

    @pytest.mark.asyncio
    async def test_refund_failure_does_not_prevent_error_propagation(self, venue_adapter, mock_client):
        """Test that refund failure doesn't prevent original error from propagating."""
        # Setup: Mock KalshiBusinessError on place_order
        business_error = KalshiBusinessError(
            "Invalid ticker",
            status_code=400,
            reason_code=2
        )
        mock_client.place_order.side_effect = business_error

        # Create test order
        order = VenueOrder(
            market_id="KXBTC15M-26JUL020700-00",
            side="buy",
            size=Decimal("100"),
            price=Decimal("0.50"),
            order_type="limit",
            client_order_id="test_agent_123"
        )

        # Mock risk envelope that fails on refund
        mock_envelope = MagicMock()
        mock_envelope.refund_order_execution.side_effect = Exception("Refund failed")

        with patch(
            'merid.risk.profiles.kalshi_crypto_15m_risk_envelope.get_kalshi_crypto_15m_risk_envelope',
            return_value=mock_envelope
        ):
            # Submit order should still raise original error
            with pytest.raises(RuntimeError, match="Order submission failed"):
                await venue_adapter._submit_live_order(order)

    @pytest.mark.asyncio
    async def test_zero_notional_no_refund(self, venue_adapter, mock_client):
        """Test that zero notional orders don't trigger refund."""
        # Setup: Mock KalshiBusinessError on place_order
        business_error = KalshiBusinessError(
            "Invalid ticker",
            status_code=400,
            reason_code=2
        )
        mock_client.place_order.side_effect = business_error

        # Create test order with zero price
        order = VenueOrder(
            market_id="KXBTC15M-26JUL020700-00",
            side="buy",
            size=Decimal("100"),
            price=Decimal("0.00"),  # Zero price
            order_type="limit",
            client_order_id="test_agent_123"
        )

        # Mock risk envelope
        mock_envelope = MagicMock()
        mock_envelope.refund_order_execution = MagicMock()

        with patch(
            'merid.risk.profiles.kalshi_crypto_15m_risk_envelope.get_kalshi_crypto_15m_risk_envelope',
            return_value=mock_envelope
        ):
            # Submit order should raise but NOT refund (zero notional)
            with pytest.raises(RuntimeError, match="Order submission failed"):
                await venue_adapter._submit_live_order(order)

        # Verify refund was NOT called (zero notional)
        mock_envelope.refund_order_execution.assert_not_called()

    @pytest.mark.asyncio
    async def test_missing_client_order_id_uses_fallback(self, venue_adapter, mock_client):
        """Test that missing client_order_id uses fallback agent_id."""
        # Setup: Mock KalshiBusinessError on place_order
        business_error = KalshiBusinessError(
            "Invalid ticker",
            status_code=400,
            reason_code=2
        )
        mock_client.place_order.side_effect = business_error

        # Create test order without client_order_id
        order = VenueOrder(
            market_id="KXBTC15M-26JUL020700-00",
            side="buy",
            size=Decimal("100"),
            price=Decimal("0.50"),
            order_type="limit"
            # No client_order_id
        )

        # Mock risk envelope
        mock_envelope = MagicMock()
        mock_envelope.refund_order_execution = MagicMock()

        with patch(
            'merid.risk.profiles.kalshi_crypto_15m_risk_envelope.get_kalshi_crypto_15m_risk_envelope',
            return_value=mock_envelope
        ):
            # Submit order should raise and refund with fallback agent_id
            with pytest.raises(RuntimeError, match="Order submission failed"):
                await venue_adapter._submit_live_order(order)

        # Verify refund was called with fallback agent_id
        mock_envelope.refund_order_execution.assert_called_once()
        call_args = mock_envelope.refund_order_execution.call_args
        assert call_args[1]['agent_id'] == "venue_adapter"  # Fallback
