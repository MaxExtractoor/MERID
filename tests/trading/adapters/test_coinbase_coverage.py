"""Comprehensive tests for trading/adapters/coinbase.py - Coverage improvement."""

import pytest
from unittest.mock import MagicMock, patch

from trading.adapters.base import TradeRequest, TradeSide, OrderType
from trading.adapters.coinbase import CoinbaseSpotAdapter


@pytest.fixture
def adapter(monkeypatch):
    """Create CoinbaseSpotAdapter with mocked exchange."""
    monkeypatch.setenv("MERID_COINBASE_API_KEY", "test_key")
    monkeypatch.setenv("MERID_COINBASE_API_SECRET", "test_secret")
    
    with patch.object(CoinbaseSpotAdapter, "_build_exchange") as mock_build:
        mock_exchange = MagicMock()
        mock_build.return_value = mock_exchange
        adapter = CoinbaseSpotAdapter()
        adapter._exchange = mock_exchange
        return adapter


@pytest.fixture
def mock_adapter(monkeypatch):
    """Create CoinbaseSpotAdapter in mock mode (no credentials)."""
    monkeypatch.delenv("MERID_COINBASE_API_KEY", raising=False)
    monkeypatch.delenv("MERID_COINBASE_API_SECRET", raising=False)
    
    adapter = CoinbaseSpotAdapter()
    return adapter


# =============================================================================
# Initialization Tests
# =============================================================================

class TestCoinbaseSpotAdapterInit:
    """Test CoinbaseSpotAdapter initialization."""

    def test_init_with_credentials(self, monkeypatch):
        monkeypatch.setenv("MERID_COINBASE_API_KEY", "test_key")
        monkeypatch.setenv("MERID_COINBASE_API_SECRET", "test_secret")
        
        with patch.object(CoinbaseSpotAdapter, "_build_exchange") as mock_build:
            mock_build.return_value = MagicMock()
            adapter = CoinbaseSpotAdapter()
        
        assert adapter.venue == "coinbase"
        assert adapter.supports_trading is True
        assert adapter.use_mock is False

    def test_init_without_credentials(self, monkeypatch):
        monkeypatch.delenv("MERID_COINBASE_API_KEY", raising=False)
        monkeypatch.delenv("MERID_COINBASE_API_SECRET", raising=False)
        
        adapter = CoinbaseSpotAdapter()
        
        assert adapter.use_mock is True
        assert adapter._exchange is None

    def test_init_with_custom_exchange_id(self, monkeypatch):
        monkeypatch.setenv("MERID_COINBASE_API_KEY", "test_key")
        monkeypatch.setenv("MERID_COINBASE_API_SECRET", "test_secret")
        
        with patch.object(CoinbaseSpotAdapter, "_build_exchange") as mock_build:
            mock_build.return_value = MagicMock()
            adapter = CoinbaseSpotAdapter(exchange_id="coinbase")
        
        assert adapter.exchange_id == "coinbase"

    def test_init_with_passphrase(self, monkeypatch):
        monkeypatch.setenv("MERID_COINBASE_API_KEY", "test_key")
        monkeypatch.setenv("MERID_COINBASE_API_SECRET", "test_secret")
        monkeypatch.setenv("MERID_COINBASE_API_PASSPHRASE", "test_pass")
        
        with patch.object(CoinbaseSpotAdapter, "_build_exchange") as mock_build:
            mock_build.return_value = MagicMock()
            adapter = CoinbaseSpotAdapter()
        
        assert adapter.passphrase == "test_pass"


# =============================================================================
# Build Exchange Tests
# =============================================================================

class TestBuildExchange:
    """Test _build_exchange method."""

    def test_build_exchange_success(self, monkeypatch):
        monkeypatch.setenv("MERID_COINBASE_API_KEY", "test_key")
        monkeypatch.setenv("MERID_COINBASE_API_SECRET", "test_secret")
        
        mock_ccxt = MagicMock()
        mock_exchange_cls = MagicMock()
        mock_ccxt.coinbasepro = mock_exchange_cls
        
        with patch.dict("sys.modules", {"ccxt": mock_ccxt}):
            adapter = CoinbaseSpotAdapter()
            # Force rebuild
            adapter._exchange = adapter._build_exchange()
        
        mock_exchange_cls.assert_called()

    def test_build_exchange_with_passphrase(self, monkeypatch):
        monkeypatch.setenv("MERID_COINBASE_API_KEY", "test_key")
        monkeypatch.setenv("MERID_COINBASE_API_SECRET", "test_secret")
        monkeypatch.setenv("MERID_COINBASE_API_PASSPHRASE", "test_pass")
        
        mock_ccxt = MagicMock()
        mock_exchange_cls = MagicMock()
        mock_ccxt.coinbasepro = mock_exchange_cls
        
        with patch.dict("sys.modules", {"ccxt": mock_ccxt}):
            adapter = CoinbaseSpotAdapter()
            adapter._exchange = adapter._build_exchange()
        
        call_args = mock_exchange_cls.call_args[0][0]
        assert call_args["password"] == "test_pass"


# =============================================================================
# Submit Order Tests
# =============================================================================

class TestSubmitOrderLive:
    """Test _submit_order_live method."""

    def test_submit_order_no_exchange(self, mock_adapter):
        """Test order submission with no exchange raises error."""
        request = TradeRequest(
            venue="coinbase",
            symbol="BTC/USD",
            side=TradeSide.BUY,
            quantity=0.1
        )
        
        with pytest.raises(RuntimeError, match="verify API credentials"):
            mock_adapter._submit_order_live(request)

    def test_submit_market_order_buy(self, adapter):
        """Test market buy order submission."""
        adapter._exchange.create_market_order.return_value = {
            "id": "order_123",
            "status": "closed",
            "average": 50000.0,
            "fills": [{"price": 50000.0, "qty": 0.1}]
        }
        
        request = TradeRequest(
            venue="coinbase",
            symbol="BTC/USD",
            side=TradeSide.BUY,
            quantity=0.1
        )
        
        result = adapter._submit_order_live(request)
        
        assert result.venue == "coinbase"
        assert result.symbol == "BTC/USD"
        assert result.side == TradeSide.BUY
        assert result.executed_price == 50000.0

    def test_submit_market_order_sell(self, adapter):
        """Test market sell order submission."""
        adapter._exchange.create_market_order.return_value = {
            "id": "order_456",
            "status": "closed",
            "average": 49000.0
        }
        
        request = TradeRequest(
            venue="coinbase",
            symbol="ETH/USD",
            side=TradeSide.SELL,
            quantity=1.0
        )
        
        result = adapter._submit_order_live(request)
        
        assert result.side == TradeSide.SELL

    def test_submit_order_symbol_without_slash(self, adapter):
        """Test order with symbol without slash gets USD appended."""
        adapter._exchange.create_market_order.return_value = {
            "id": "order_789",
            "status": "closed",
            "average": 100.0
        }
        
        request = TradeRequest(
            venue="coinbase",
            symbol="SOL",
            side=TradeSide.BUY,
            quantity=10.0
        )
        
        result = adapter._submit_order_live(request)
        
        assert result.symbol == "SOL/USD"

    def test_submit_limit_order_success(self, adapter):
        """Test successful limit order submission."""
        adapter._exchange.create_limit_order.return_value = {
            "id": "limit_order_1",
            "status": "open",
            "price": 48000.0
        }
        
        request = TradeRequest(
            venue="coinbase",
            symbol="BTC/USD",
            side=TradeSide.BUY,
            quantity=0.1,
            order_type=OrderType.LIMIT,
            price=48000.0
        )
        
        result = adapter._submit_order_live(request)
        
        adapter._exchange.create_limit_order.assert_called_once()
        assert result.executed_price == 48000.0

    def test_submit_limit_order_no_price_raises(self, adapter):
        """Test limit order without price raises error."""
        request = TradeRequest(
            venue="coinbase",
            symbol="BTC/USD",
            side=TradeSide.BUY,
            quantity=0.1,
            order_type=OrderType.LIMIT,
            price=None
        )
        
        with pytest.raises(RuntimeError, match="Limit orders require a price"):
            adapter._submit_order_live(request)

    def test_submit_order_exchange_error(self, adapter):
        """Test order submission with exchange error."""
        adapter._exchange.create_market_order.side_effect = Exception("Exchange error")
        
        request = TradeRequest(
            venue="coinbase",
            symbol="BTC/USD",
            side=TradeSide.BUY,
            quantity=0.1
        )
        
        with pytest.raises(Exception, match="Exchange error"):
            adapter._submit_order_live(request)
        
        assert adapter._last_error == "Exchange error"

    def test_submit_order_price_fallback(self, adapter):
        """Test order with price fallback when no average."""
        adapter._exchange.create_market_order.return_value = {
            "id": "order_fallback",
            "status": "closed"
        }
        
        request = TradeRequest(
            venue="coinbase",
            symbol="BTC/USD",
            side=TradeSide.BUY,
            quantity=0.1,
            price=51000.0
        )
        
        result = adapter._submit_order_live(request)
        
        assert result.executed_price == 51000.0


# =============================================================================
# Class Attributes Tests
# =============================================================================

class TestClassAttributes:
    """Test class-level attributes."""

    def test_venue_name(self):
        assert CoinbaseSpotAdapter.venue == "coinbase"

    def test_supports_trading(self):
        assert CoinbaseSpotAdapter.supports_trading is True
