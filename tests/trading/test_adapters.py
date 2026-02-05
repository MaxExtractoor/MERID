"""Tests for trading adapters - Batch 6 Coverage."""
import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from datetime import datetime

from trading.adapters.alpaca import AlpacaEquitiesAdapter
from trading.adapters.coinbase import CoinbaseSpotAdapter
from trading.adapters.kalshi import KalshiPredictionAdapter
from trading.adapters.base import TradeRequest, TradeSide, OrderType, OrderResult, BalanceSnapshot, PositionSnapshot


class TestAlpacaEquitiesAdapter:
    """Tests for Alpaca equities adapter."""

    @pytest.fixture
    def adapter(self):
        """Create AlpacaEquitiesAdapter instance with mocked client."""
        with patch('trading.adapters.alpaca.get_alpaca_client') as mock_client:
            mock_cl = MagicMock()
            mock_client.return_value = mock_cl
            return AlpacaEquitiesAdapter()

    def test_initialization_with_client(self, adapter):
        """Test adapter initialization with client."""
        assert adapter is not None
        assert adapter.venue == "alpaca"
        assert adapter.supports_trading is True
        assert adapter._client is not None

    def test_initialization_without_client(self):
        """Test adapter initialization without client falls back to mock."""
        with patch('trading.adapters.alpaca.get_alpaca_client') as mock_client:
            mock_client.side_effect = Exception("No credentials")
            adapter = AlpacaEquitiesAdapter()
            assert adapter._client is None
            assert adapter.use_mock is True

    def test_get_balances_live(self, adapter):
        """Test getting balances."""
        with patch('trading.adapters.alpaca.fetch_account_snapshot') as mock_fetch:
            mock_fetch.return_value = {
                "cash": "10000.00",
                "portfolio_value": "25000.00"
            }
            balances = adapter._get_balances_live()

            assert len(balances) == 1
            assert balances[0].asset == "USD"
            assert balances[0].available == 10000.00
            assert balances[0].total == 25000.00

    def test_get_positions_live(self, adapter):
        """Test getting positions."""
        mock_position = MagicMock()
        mock_position.symbol = "AAPL"
        mock_position.qty = "10"
        mock_position._raw = {
            "symbol": "AAPL",
            "qty": "10",
            "avg_entry_price": "150.00",
            "current_price": "155.00",
            "unrealized_pl": "50.00"
        }
        adapter._client.list_positions.return_value = [mock_position]

        positions = adapter._get_positions_live()

        assert len(positions) == 1
        assert positions[0].symbol == "AAPL"
        assert positions[0].quantity == 10.0

    def test_get_positions_live_no_client(self, adapter):
        """Test getting positions when no client."""
        adapter._client = None
        positions = adapter._get_positions_live()
        assert positions == []

    def test_get_positions_live_error(self, adapter):
        """Test position fetch error handling."""
        adapter._client.list_positions.side_effect = Exception("Network error")
        positions = adapter._get_positions_live()
        assert positions == []

    def test_submit_order_live_market(self, adapter):
        """Test submitting market order."""
        mock_order = MagicMock()
        mock_order.id = "order_123"
        mock_order._raw = {
            "id": "order_123",
            "filled_avg_price": "150.00",
            "filled_qty": "10",
            "status": "filled"
        }
        adapter._client.submit_order.return_value = mock_order

        request = TradeRequest(
            venue="alpaca",
            symbol="AAPL",
            side=TradeSide.BUY,
            quantity=10,
            order_type=OrderType.MARKET
        )

        result = adapter._submit_order_live(request)

        assert result.venue == "alpaca"
        assert result.symbol == "AAPL"
        assert result.status == "filled"
        assert result.quantity == 10.0

    def test_submit_order_live_limit(self, adapter):
        """Test submitting limit order."""
        mock_order = MagicMock()
        mock_order.id = "order_456"
        mock_order._raw = {
            "id": "order_456",
            "filled_avg_price": "200.00",
            "filled_qty": "5",
            "status": "filled"
        }
        adapter._client.submit_order.return_value = mock_order

        request = TradeRequest(
            venue="alpaca",
            symbol="TSLA",
            side=TradeSide.SELL,
            quantity=5,
            order_type=OrderType.LIMIT,
            price=200.00
        )

        result = adapter._submit_order_live(request)

        assert result.executed_price == 200.00
        assert result.quantity == 5.0

    def test_submit_order_live_no_client(self, adapter):
        """Test submitting order without client raises error."""
        adapter._client = None
        request = TradeRequest(venue="alpaca", symbol="AAPL", side=TradeSide.BUY, quantity=10)
        with pytest.raises(RuntimeError, match="Alpaca adapter unavailable"):
            adapter._submit_order_live(request)

    def test_submit_order_live_limit_no_price(self, adapter):
        """Test limit order without price raises error."""
        request = TradeRequest(
            venue="alpaca",
            symbol="AAPL",
            side=TradeSide.BUY,
            quantity=10,
            order_type=OrderType.LIMIT
        )
        with pytest.raises(RuntimeError, match="Limit orders require price"):
            adapter._submit_order_live(request)


class TestTradeRequest:
    """Tests for TradeRequest dataclass."""

    def test_basic_creation(self):
        """Test creating a basic trade request."""
        request = TradeRequest(
            venue="alpaca",
            symbol="AAPL",
            side=TradeSide.BUY,
            quantity=100
        )
        assert request.symbol == "AAPL"
        assert request.side == TradeSide.BUY
        assert request.quantity == 100

    def test_with_limit_order(self):
        """Test creating limit order request."""
        request = TradeRequest(
            venue="alpaca",
            symbol="TSLA",
            side=TradeSide.SELL,
            quantity=50,
            order_type=OrderType.LIMIT,
            price=200.00
        )
        assert request.order_type == OrderType.LIMIT
        assert request.price == 200.00

    def test_with_client_reference(self):
        """Test trade request with client reference."""
        request = TradeRequest(
            venue="coinbase",
            symbol="BTC-USD",
            side=TradeSide.BUY,
            quantity=1,
            client_reference="my_order_123"
        )
        assert request.client_reference == "my_order_123"


class TestTradeSide:
    """Tests for TradeSide enum."""

    def test_buy_value(self):
        """Test BUY side value."""
        assert TradeSide.BUY.value == "buy"

    def test_sell_value(self):
        """Test SELL side value."""
        assert TradeSide.SELL.value == "sell"


class TestOrderResult:
    """Tests for OrderResult dataclass."""

    def test_successful_order(self):
        """Test successful order result."""
        result = OrderResult(
            venue="alpaca",
            symbol="AAPL",
            side=TradeSide.BUY,
            quantity=100,
            executed_price=150.00,
            status="filled",
            venue_order_id="order_123"
        )
        assert result.venue == "alpaca"
        assert result.quantity == 100
        assert result.status == "filled"

    def test_order_with_metadata(self):
        """Test order result with metadata."""
        result = OrderResult(
            venue="coinbase",
            symbol="BTC-USD",
            side=TradeSide.SELL,
            quantity=0.5,
            executed_price=45000.00,
            status="filled",
            metadata={"fills": [{"price": 45000, "qty": 0.5}]}
        )
        assert "fills" in result.metadata


class TestBalanceSnapshot:
    """Tests for BalanceSnapshot dataclass."""

    def test_creation(self):
        """Test creating balance snapshot."""
        snapshot = BalanceSnapshot(
            asset="USD",
            total=25000.00,
            available=10000.00,
            usd_value=25000.00
        )
        assert snapshot.asset == "USD"
        assert snapshot.total == 25000.00
        assert snapshot.available == 10000.00

    def test_with_metadata(self):
        """Test balance with metadata."""
        snapshot = BalanceSnapshot(
            asset="BTC",
            total=1.5,
            available=1.0,
            usd_value=67500.00,
            metadata={"wallet_address": "0x123"}
        )
        assert snapshot.metadata["wallet_address"] == "0x123"


class TestPositionSnapshot:
    """Tests for PositionSnapshot dataclass."""

    def test_creation(self):
        """Test creating position snapshot."""
        position = PositionSnapshot(
            symbol="AAPL",
            quantity=100,
            entry_price=150.00,
            mark_price=155.00,
            unrealized_pnl=500.00
        )
        assert position.symbol == "AAPL"
        assert position.quantity == 100
        assert position.unrealized_pnl == 500.00


class TestCoinbaseSpotAdapter:
    """Tests for Coinbase spot adapter."""

    @pytest.fixture
    def adapter(self):
        """Create CoinbaseSpotAdapter instance with mocked exchange."""
        with patch.dict('os.environ', {
            'MERID_COINBASE_API_KEY': 'test_key',
            'MERID_COINBASE_API_SECRET': 'test_secret'
        }):
            # ccxt is imported inside the method, so mock the import itself
            mock_ccxt = MagicMock()
            mock_exchange = MagicMock()
            mock_ccxt.coinbasepro = MagicMock(return_value=mock_exchange)
            
            with patch.dict('sys.modules', {'ccxt': mock_ccxt}):
                adapter = CoinbaseSpotAdapter()
                adapter._exchange = mock_exchange
                return adapter

    def test_initialization_without_creds(self):
        """Test adapter initialization without credentials falls back to mock."""
        with patch.dict('os.environ', {}, clear=True):
            adapter = CoinbaseSpotAdapter()
            assert adapter.use_mock is True
            assert adapter._exchange is None

    def test_get_balances_live_no_exchange(self):
        """Test getting balances when no exchange."""
        with patch.dict('os.environ', {
            'MERID_COINBASE_API_KEY': 'test_key',
            'MERID_COINBASE_API_SECRET': 'test_secret'
        }):
            mock_ccxt = MagicMock()
            mock_exchange = MagicMock()
            mock_ccxt.coinbasepro = MagicMock(return_value=mock_exchange)
            
            with patch.dict('sys.modules', {'ccxt': mock_ccxt}):
                adapter = CoinbaseSpotAdapter()
                adapter._exchange = None
                balances = adapter._get_balances_live()
                assert balances == []

    def test_submit_order_live_no_exchange(self):
        """Test submitting order without exchange raises error."""
        with patch.dict('os.environ', {
            'MERID_COINBASE_API_KEY': 'test_key',
            'MERID_COINBASE_API_SECRET': 'test_secret'
        }):
            mock_ccxt = MagicMock()
            mock_exchange = MagicMock()
            mock_ccxt.coinbasepro = MagicMock(return_value=mock_exchange)
            
            with patch.dict('sys.modules', {'ccxt': mock_ccxt}):
                adapter = CoinbaseSpotAdapter()
                adapter._exchange = None
                request = TradeRequest(
                    venue="coinbase",
                    symbol="BTCUSD",
                    side=TradeSide.BUY,
                    quantity=0.5
                )
                with pytest.raises(RuntimeError, match="Coinbase adapter unavailable"):
                    adapter._submit_order_live(request)


class TestKalshiPredictionAdapter:
    """Tests for Kalshi prediction market adapter."""

    @pytest.fixture
    def adapter(self):
        """Create KalshiPredictionAdapter instance with mocked client."""
        with patch('trading.adapters.kalshi.get_kalshi_client') as mock_client:
            mock_cl = MagicMock()
            mock_client.return_value = mock_cl
            return KalshiPredictionAdapter()

    def test_initialization(self, adapter):
        """Test adapter initialization."""
        assert adapter is not None
        assert adapter.venue == "kalshi"
        assert adapter.supports_trading is False

    def test_initialization_without_client(self):
        """Test adapter initialization without client falls back to mock."""
        with patch('trading.adapters.kalshi.get_kalshi_client') as mock_client:
            mock_client.side_effect = Exception("No credentials")
            adapter = KalshiPredictionAdapter()
            assert adapter._client is None
            assert adapter.use_mock is True

    def test_get_balances_live(self, adapter):
        """Test getting balances from Kalshi."""
        with patch('trading.adapters.kalshi.fetch_kalshi_balance') as mock_fetch:
            mock_fetch.return_value = {
                "balance": 500000,
                "raw": {"balance": "5000.00"}
            }
            balances = adapter._get_balances_live()

            assert len(balances) == 1
            assert balances[0].asset == "USD"
            assert balances[0].total == 5000.00

    def test_get_balances_live_error(self, adapter):
        """Test balance fetch error handling."""
        with patch('trading.adapters.kalshi.fetch_kalshi_balance') as mock_fetch:
            mock_fetch.return_value = {"balance": None}
            balances = adapter._get_balances_live()

            assert len(balances) == 1
            assert balances[0].total == 0.0


class TestOrderType:
    """Tests for OrderType enum."""

    def test_market_order(self):
        """Test MARKET order type."""
        assert OrderType.MARKET.value == "market"

    def test_limit_order(self):
        """Test LIMIT order type."""
        assert OrderType.LIMIT.value == "limit"

    def test_ioc_order(self):
        """Test IOC order type."""
        assert OrderType.IOC.value == "ioc"

    def test_fok_order(self):
        """Test FOK order type."""
        assert OrderType.FOK.value == "fok"
