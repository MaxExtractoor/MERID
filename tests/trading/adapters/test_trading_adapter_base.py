"""Tests for trading/adapters/base.py."""
import pytest
from unittest.mock import patch
from trading.adapters.base import (
    TradeSide, OrderType, TradeRequest, OrderResult, 
    BalanceSnapshot, PositionSnapshot, VenueHealth,
    TradingVenueAdapterBase
)


class TestTradeSide:
    """Test TradeSide enum."""

    def test_trade_side_values(self):
        """Test TradeSide enum values."""
        assert TradeSide.BUY == "buy"
        assert TradeSide.SELL == "sell"


class TestOrderType:
    """Test OrderType enum."""

    def test_order_type_values(self):
        """Test OrderType enum values."""
        assert OrderType.MARKET == "market"
        assert OrderType.LIMIT == "limit"
        assert OrderType.IOC == "ioc"
        assert OrderType.FOK == "fok"


class TestTradeRequest:
    """Test TradeRequest dataclass."""

    def test_creation(self):
        """Test TradeRequest creation."""
        request = TradeRequest(
            venue="coinbase",
            symbol="BTC-USD",
            side=TradeSide.BUY,
            quantity=1.0,
            order_type=OrderType.LIMIT,
            price=50000.0,
            notional_usd=50000.0,
            client_reference="ref_123",
            metadata={"source": "api"},
            live=True
        )
        assert request.venue == "coinbase"
        assert request.symbol == "BTC-USD"
        assert request.side == TradeSide.BUY
        assert request.quantity == 1.0
        assert request.order_type == OrderType.LIMIT
        assert request.price == 50000.0
        assert request.notional_usd == 50000.0
        assert request.client_reference == "ref_123"
        assert request.metadata == {"source": "api"}
        assert request.live is True

    def test_defaults(self):
        """Test TradeRequest defaults."""
        request = TradeRequest(
            venue="kraken",
            symbol="ETH-USD",
            side=TradeSide.SELL,
            quantity=2.0
        )
        assert request.order_type == OrderType.MARKET
        assert request.price is None
        assert request.live is False


class TestOrderResult:
    """Test OrderResult dataclass."""

    def test_creation(self):
        """Test OrderResult creation."""
        result = OrderResult(
            venue="coinbase",
            symbol="BTC-USD",
            side=TradeSide.BUY,
            quantity=1.0,
            executed_price=50000.0,
            status="filled",
            venue_order_id="ord_123",
            transaction_hash="tx_456",
            metadata={"fee": "0.5%"}
        )
        assert result.venue == "coinbase"
        assert result.status == "filled"
        assert result.venue_order_id == "ord_123"


class TestBalanceSnapshot:
    """Test BalanceSnapshot dataclass."""

    def test_creation(self):
        """Test BalanceSnapshot creation."""
        balance = BalanceSnapshot(
            asset="BTC",
            total=10.0,
            available=8.0,
            usd_value=500000.0,
            metadata={"locked": 2.0}
        )
        assert balance.asset == "BTC"
        assert balance.total == 10.0
        assert balance.available == 8.0
        assert balance.usd_value == 500000.0


class TestPositionSnapshot:
    """Test PositionSnapshot dataclass."""

    def test_creation(self):
        """Test PositionSnapshot creation."""
        position = PositionSnapshot(
            symbol="BTC-USD",
            quantity=1.0,
            entry_price=45000.0,
            mark_price=50000.0,
            unrealized_pnl=5000.0,
            metadata={"leverage": 1.0}
        )
        assert position.symbol == "BTC-USD"
        assert position.quantity == 1.0
        assert position.entry_price == 45000.0
        assert position.unrealized_pnl == 5000.0


class TestVenueHealth:
    """Test VenueHealth dataclass."""

    def test_creation(self):
        """Test VenueHealth creation."""
        health = VenueHealth(
            venue="coinbase",
            status="online",
            last_updated=1234567890.0,
            latency_ms=150.0,
            last_error=None,
            metadata={"region": "us-east"}
        )
        assert health.venue == "coinbase"
        assert health.status == "online"
        assert health.latency_ms == 150.0


class MockTradingAdapter(TradingVenueAdapterBase):
    """Mock adapter for testing base class."""
    venue = "mock"
    supported_assets = ("BTC", "ETH")
    supports_trading = True

    def _get_balances_live(self):
        return []

    def _get_positions_live(self):
        return []

    def _submit_order_live(self, request):
        return OrderResult(
            venue=self.venue,
            symbol=request.symbol,
            side=request.side,
            quantity=request.quantity,
            executed_price=100.0,
            status="filled"
        )

    def _cancel_order_live(self, venue_order_id):
        return True


class TestTradingVenueAdapterBase:
    """Test TradingVenueAdapterBase class."""

    def test_initialization_mock_mode(self):
        """Test initialization in mock mode without API key."""
        adapter = MockTradingAdapter()
        assert adapter.use_mock is True
        assert adapter._client is None

    @patch.dict('os.environ', {'MERID_MOCK_API_KEY': 'test_key'})
    def test_initialization_live_mode(self):
        """Test initialization with API key from environment."""
        adapter = MockTradingAdapter()
        assert adapter.api_key == 'test_key'
        assert adapter.use_mock is False
        assert adapter._client is not None

    def test_explicit_mock_override(self):
        """Test explicit use_mock parameter."""
        adapter = MockTradingAdapter(use_mock=True)
        assert adapter.use_mock is True

    def test_get_health_mock_mode(self):
        """Test get_health in mock mode."""
        adapter = MockTradingAdapter()
        health = adapter.get_health()
        assert health.venue == "mock"
        assert health.status == "offline"
        assert health.metadata["supports_trading"] is True

    def test_get_health_with_error(self):
        """Test get_health when last_error is set."""
        adapter = MockTradingAdapter()
        adapter._last_error = "Connection failed"
        health = adapter.get_health()
        assert health.status == "degraded"
        assert health.last_error == "Connection failed"

    def test_get_balances_mock_mode(self):
        """Test get_balances in mock mode returns empty."""
        adapter = MockTradingAdapter()
        balances = adapter.get_balances()
        assert balances == []

    def test_get_positions_mock_mode(self):
        """Test get_positions in mock mode returns empty."""
        adapter = MockTradingAdapter()
        positions = adapter.get_positions()
        assert positions == []

    def test_submit_order_mock_mode_raises(self):
        """Test submit_order in mock mode raises RuntimeError."""
        adapter = MockTradingAdapter()
        request = TradeRequest(
            venue="mock",
            symbol="BTC",
            side=TradeSide.BUY,
            quantity=1.0
        )
        with pytest.raises(RuntimeError, match="mock mode"):
            adapter.submit_order(request)

    def test_submit_order_read_only_raises(self):
        """Test submit_order when supports_trading is False."""
        class ReadOnlyAdapter(MockTradingAdapter):
            supports_trading = False

        adapter = ReadOnlyAdapter(use_mock=False)
        request = TradeRequest(
            venue="readonly",
            symbol="BTC",
            side=TradeSide.BUY,
            quantity=1.0
        )
        with pytest.raises(RuntimeError, match="read-only"):
            adapter.submit_order(request)

    def test_cancel_order_mock_mode(self):
        """Test cancel_order in mock mode returns False."""
        adapter = MockTradingAdapter()
        result = adapter.cancel_order("order_123")
        assert result is False

    def test_record_latency(self):
        """Test _record_latency updates metrics."""
        import time
        adapter = MockTradingAdapter()
        start = time.perf_counter()
        adapter._record_latency(start)
        assert adapter._last_latency_ms is not None
        assert adapter._last_latency_ms >= 0
        assert adapter._last_error is None
