"""Tests for trading/adapters/coinbase.py."""
import pytest
from unittest.mock import Mock, patch, MagicMock
from trading.adapters.coinbase import CoinbaseSpotAdapter
from trading.adapters.base import TradeRequest, TradeSide, OrderType


class TestCoinbaseSpotAdapter:
    """Test CoinbaseSpotAdapter class."""

    def test_initialization_mock_mode(self):
        """Test initialization in mock mode without API key."""
        adapter = CoinbaseSpotAdapter()
        assert adapter.venue == "coinbase"
        assert adapter.supports_trading is True
        assert adapter.use_mock is True
        assert adapter._exchange is None

    @patch.dict('os.environ', {'MERID_COINBASE_API_KEY': 'test_key', 'MERID_COINBASE_API_SECRET': 'test_secret'})
    def test_initialization_with_credentials(self):
        """Test initialization with API credentials."""
        adapter = CoinbaseSpotAdapter()
        assert adapter.api_key == 'test_key'
        assert adapter.api_secret == 'test_secret'

    def test_custom_exchange_id(self):
        """Test custom exchange ID."""
        adapter = CoinbaseSpotAdapter(exchange_id="coinbase")
        assert adapter.exchange_id == "coinbase"

    @patch.dict('os.environ', {'MERID_COINBASE_EXCHANGE_ID': 'coinbasepro'})
    def test_exchange_id_from_env(self):
        """Test exchange ID from environment."""
        adapter = CoinbaseSpotAdapter()
        assert adapter.exchange_id == "coinbasepro"

    def test_submit_order_live_no_exchange_raises(self):
        """Test submit_order_live raises when exchange not initialized."""
        adapter = CoinbaseSpotAdapter()  # No API key, use_mock=True
        # Manually set use_mock to False to test the check
        adapter.use_mock = False
        adapter._exchange = None

        request = TradeRequest(
            venue="coinbase",
            symbol="BTC",
            side=TradeSide.BUY,
            quantity=0.1
        )

        with pytest.raises(RuntimeError, match="unavailable"):
            adapter._submit_order_live(request)

    def test_build_exchange_mock_mode_on_error(self):
        """Test _build_exchange sets use_mock on error."""
        adapter = CoinbaseSpotAdapter()
        adapter.api_key = "test_key"  # Set to not use mock initially
        adapter.use_mock = False

        # _build_exchange will fail because ccxt is not available
        result = adapter._build_exchange()

        # Should return None and set use_mock to True
        assert result is None or adapter.use_mock is True

    def test_symbol_formatting_with_slash(self):
        """Test symbol with slash is preserved."""
        adapter = CoinbaseSpotAdapter()
        adapter._exchange = MagicMock()
        adapter._exchange.create_market_order.return_value = {
            "id": "ord_123",
            "price": 50000.0,
            "status": "filled"
        }

        request = TradeRequest(
            venue="coinbase",
            symbol="BTC/USD",  # Already has slash
            side=TradeSide.BUY,
            quantity=0.1,
            order_type=OrderType.MARKET
        )

        result = adapter._submit_order_live(request)

        # Symbol should remain BTC/USD
        assert "BTC/USD" in str(adapter._exchange.create_market_order.call_args)

    def test_symbol_formatting_without_slash(self):
        """Test symbol without slash gets /USD appended."""
        adapter = CoinbaseSpotAdapter()
        adapter._exchange = MagicMock()
        adapter._exchange.create_market_order.return_value = {
            "id": "ord_123",
            "price": 50000.0,
            "status": "filled"
        }

        request = TradeRequest(
            venue="coinbase",
            symbol="BTC",  # No slash
            side=TradeSide.BUY,
            quantity=0.1,
            order_type=OrderType.MARKET
        )

        result = adapter._submit_order_live(request)

        # Should have called with BTC/USD
        call_args = adapter._exchange.create_market_order.call_args[0]
        assert "BTC/USD" in call_args

    def test_market_order(self):
        """Test market order execution."""
        adapter = CoinbaseSpotAdapter()
        adapter._exchange = MagicMock()
        adapter._exchange.create_market_order.return_value = {
            "id": "ord_123",
            "price": 50000.0,
            "average": 50000.0,
            "status": "filled",
            "fills": [{"price": 50000.0, "amount": 0.1}]
        }

        request = TradeRequest(
            venue="coinbase",
            symbol="BTC/USD",
            side=TradeSide.BUY,
            quantity=0.1,
            order_type=OrderType.MARKET
        )

        result = adapter._submit_order_live(request)

        assert result.venue == "coinbase"
        assert result.symbol == "BTC/USD"
        assert result.side == TradeSide.BUY
        assert result.quantity == 0.1
        assert result.executed_price == 50000.0
        assert result.status == "filled"
        assert result.venue_order_id == "ord_123"
        adapter._exchange.create_market_order.assert_called_once()

    def test_limit_order_with_price(self):
        """Test limit order with price."""
        adapter = CoinbaseSpotAdapter()
        adapter._exchange = MagicMock()
        adapter._exchange.create_limit_order.return_value = {
            "id": "ord_456",
            "price": 49000.0,
            "status": "open"
        }

        request = TradeRequest(
            venue="coinbase",
            symbol="BTC/USD",
            side=TradeSide.SELL,
            quantity=0.1,
            order_type=OrderType.LIMIT,
            price=49000.0
        )

        result = adapter._submit_order_live(request)

        assert result.side == TradeSide.SELL
        assert result.executed_price == 49000.0
        adapter._exchange.create_limit_order.assert_called_once()

    def test_limit_order_without_price_raises(self):
        """Test limit order without price raises error."""
        adapter = CoinbaseSpotAdapter()
        adapter._exchange = MagicMock()

        request = TradeRequest(
            venue="coinbase",
            symbol="BTC/USD",
            side=TradeSide.BUY,
            quantity=0.1,
            order_type=OrderType.LIMIT,
            price=None  # No price
        )

        with pytest.raises(RuntimeError, match="require a price"):
            adapter._submit_order_live(request)

    def test_sell_side_mapping(self):
        """Test sell side is mapped correctly."""
        adapter = CoinbaseSpotAdapter()
        adapter._exchange = MagicMock()
        adapter._exchange.create_market_order.return_value = {
            "id": "ord_789",
            "price": 3000.0,
            "status": "filled"
        }

        request = TradeRequest(
            venue="coinbase",
            symbol="ETH/USD",
            side=TradeSide.SELL,
            quantity=1.0,
            order_type=OrderType.MARKET
        )

        result = adapter._submit_order_live(request)

        # Check that side was mapped to "sell"
        call_args = adapter._exchange.create_market_order.call_args[0]
        assert call_args[1] == "sell"  # Second arg is side
