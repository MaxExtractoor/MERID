"""Tests for trading/adapters/kalshi.py."""
import asyncio
import sys
from types import ModuleType
from unittest.mock import MagicMock

# Stub heavy optional deps that are not installed in the test environment
for _mod in ("aiohttp", "aiohttp.client_exceptions"):
    if _mod not in sys.modules:
        sys.modules[_mod] = MagicMock()

import pytest
from decimal import Decimal
from unittest.mock import AsyncMock, Mock, patch

from trading.adapters.kalshi import KalshiPredictionAdapter
from trading.adapters.base import TradeRequest, TradeSide

# Patch target: KalshiVenueAdapter is imported lazily inside each method
_VENUE_ADAPTER_PATH = "merid.event_venues.kalshi.venue_adapter.KalshiVenueAdapter"


class TestKalshiPredictionAdapter:
    """Test KalshiPredictionAdapter class."""

    def test_initialization(self):
        """Test adapter initialization."""
        with patch('trading.adapters.kalshi.get_kalshi_client') as mock_get_client:
            mock_client = Mock()
            mock_get_client.return_value = mock_client
            
            adapter = KalshiPredictionAdapter()
            assert adapter.venue == "kalshi"
            assert adapter.supports_trading is True
            assert adapter._client is mock_client

    @patch('trading.adapters.kalshi.get_kalshi_client')
    def test_initialization_client_error(self, mock_get_client):
        """Test initialization when client fails."""
        mock_get_client.side_effect = Exception("Connection failed")
        
        adapter = KalshiPredictionAdapter()
        assert adapter.use_mock is True
        assert adapter._client is None

    @patch('trading.adapters.kalshi.fetch_kalshi_balance')
    def test_get_balances_live(self, mock_fetch_balance):
        """Test getting balances."""
        mock_fetch_balance.return_value = {
            "balance": 10000,  # In cents
            "raw": {"account_id": "acc_123"}
        }
        
        with patch('trading.adapters.kalshi.get_kalshi_client'):
            adapter = KalshiPredictionAdapter()
            balances = adapter._get_balances_live()
        
        assert len(balances) == 1
        assert balances[0].asset == "USD"
        assert balances[0].total == 100.0  # Converted from cents
        assert balances[0].available == 100.0
        assert balances[0].usd_value == 100.0
        assert balances[0].metadata == {"account_id": "acc_123"}

    @patch('trading.adapters.kalshi.fetch_kalshi_balance')
    def test_get_balances_with_none_balance(self, mock_fetch_balance):
        """Test getting balances when balance is None."""
        mock_fetch_balance.return_value = {
            "balance": None,
            "raw": {}
        }
        
        with patch('trading.adapters.kalshi.get_kalshi_client'):
            adapter = KalshiPredictionAdapter()
            balances = adapter._get_balances_live()
        
        assert len(balances) == 1
        assert balances[0].total == 0.0

    @patch('trading.adapters.kalshi.fetch_kalshi_balance')
    def test_get_balances_conversion_error(self, mock_fetch_balance):
        """Test getting balances with conversion error."""
        mock_fetch_balance.return_value = {
            "balance": "invalid",  # Will cause conversion error
            "raw": {}
        }
        
        with patch('trading.adapters.kalshi.get_kalshi_client'):
            adapter = KalshiPredictionAdapter()
            balances = adapter._get_balances_live()
        
        # Should handle error gracefully
        assert len(balances) == 1
        assert balances[0].total == 0.0

    @patch('trading.adapters.kalshi.get_kalshi_client')
    def test_submit_order_live_delegates_to_venue_adapter(self, mock_get_client):
        """_submit_order_live runs the async venue adapter and returns an OrderResult."""
        from merid.event_venues.base import PlacedOrder

        placed = PlacedOrder(
            order_id="ord_abc",
            market_id="MARKET-XYZ",
            side="buy",
            size=Decimal("10"),
            price=Decimal("0.55"),
            filled_size=Decimal("10"),
            status="filled",
        )

        request = TradeRequest(
            venue="kalshi",
            symbol="MARKET-XYZ",
            side=TradeSide.BUY,
            quantity=10.0,
            price=0.55,
        )

        adapter = KalshiPredictionAdapter()

        mock_venue = Mock()
        mock_venue.submit_order = AsyncMock(return_value=placed)

        with patch(
            'trading.adapters.kalshi.KalshiVenueAdapter',
            return_value=mock_venue,
        ):
            result = adapter._submit_order_live(request)

        assert result.status == "filled"
        assert result.venue_order_id == "ord_abc"
        assert result.executed_price == pytest.approx(0.55)

    @patch('trading.adapters.kalshi.get_kalshi_client')
    def test_submit_order_live_returns_rejected_on_error(self, mock_get_client):
        """_submit_order_live returns a rejected OrderResult when the adapter raises."""
        request = TradeRequest(
            venue="kalshi",
            symbol="MARKET-XYZ",
            side=TradeSide.BUY,
            quantity=5.0,
        )

        adapter = KalshiPredictionAdapter()

        mock_venue = Mock()
        mock_venue.submit_order = AsyncMock(side_effect=RuntimeError("API down"))

        with patch(
            'trading.adapters.kalshi.KalshiVenueAdapter',
            return_value=mock_venue,
        ):
            result = adapter._submit_order_live(request)

        assert result.status == "rejected"
        assert "API down" in result.metadata.get("error", "")

    @patch('trading.adapters.kalshi.get_kalshi_client')
    def test_get_positions_live_returns_snapshots(self, mock_get_client):
        """_get_positions_live maps VenuePosition objects to PositionSnapshot."""
        from decimal import Decimal
        from merid.event_venues.base import VenuePosition

        venue_pos = VenuePosition(
            market_id="MARKET-XYZ",
            outcome_id="yes",
            size=Decimal("5"),
            average_entry_price=Decimal("0.60"),
            unrealized_pnl=Decimal("1.50"),
            venue="kalshi",
        )

        adapter = KalshiPredictionAdapter()

        mock_venue = Mock()
        mock_venue.get_positions = AsyncMock(return_value=[venue_pos])

        with patch(
            'trading.adapters.kalshi.KalshiVenueAdapter',
            return_value=mock_venue,
        ):
            snapshots = adapter._get_positions_live()

        assert len(snapshots) == 1
        snap = snapshots[0]
        assert snap.symbol == "MARKET-XYZ"
        assert snap.quantity == 5.0
        assert snap.entry_price == pytest.approx(0.60)
        assert snap.unrealized_pnl == pytest.approx(1.50)
        assert snap.metadata["outcome_id"] == "yes"

    @patch('trading.adapters.kalshi.get_kalshi_client')
    def test_get_positions_live_returns_empty_on_error(self, mock_get_client):
        """_get_positions_live returns [] when the adapter raises."""
        adapter = KalshiPredictionAdapter()

        mock_venue = Mock()
        mock_venue.get_positions = AsyncMock(side_effect=RuntimeError("network error"))

        with patch(
            'trading.adapters.kalshi.KalshiVenueAdapter',
            return_value=mock_venue,
        ):
            snapshots = adapter._get_positions_live()

        assert snapshots == []
