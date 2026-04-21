"""Tests for trading adapters base module - Batch 38 Coverage."""
import pytest
from unittest.mock import patch, MagicMock
import os
import time

from trading.adapters.base import (
    TradeSide,
    OrderType,
    TradeRequest,
    OrderResult,
    BalanceSnapshot,
    PositionSnapshot,
    VenueHealth,
    TradingVenueAdapterBase,
)


class TestTradeSide:
    """Tests for TradeSide enum."""

    def test_trade_side_values(self):
        assert TradeSide.BUY == "buy"
        assert TradeSide.SELL == "sell"

    def test_trade_side_comparison(self):
        assert TradeSide.BUY == "buy"
        assert TradeSide.SELL == "sell"
        assert TradeSide.BUY != "sell"


class TestOrderType:
    """Tests for OrderType enum."""

    def test_order_type_values(self):
        assert OrderType.MARKET == "market"
        assert OrderType.LIMIT == "limit"
        assert OrderType.IOC == "ioc"
        assert OrderType.FOK == "fok"


class TestTradeRequest:
    """Tests for TradeRequest dataclass."""

    def test_trade_request_creation(self):
        request = TradeRequest(
            venue="binance",
            symbol="BTC/USD",
            side=TradeSide.BUY,
            quantity=1.0,
            order_type=OrderType.MARKET,
            price=50000.0,
            notional_usd=50000.0,
            client_reference="ref_123",
            metadata={"strategy": "arbitrage"},
            live=True,
        )
        assert request.venue == "binance"
        assert request.symbol == "BTC/USD"
        assert request.side == TradeSide.BUY
        assert request.quantity == 1.0
        assert request.order_type == OrderType.MARKET
        assert request.price == 50000.0
        assert request.notional_usd == 50000.0
        assert request.client_reference == "ref_123"
        assert request.metadata == {"strategy": "arbitrage"}
        assert request.live is True

    def test_trade_request_defaults(self):
        request = TradeRequest(
            venue="binance",
            symbol="BTC/USD",
            side=TradeSide.BUY,
            quantity=1.0,
        )
        assert request.order_type == OrderType.MARKET
        assert request.price is None
        assert request.notional_usd is None
        assert request.client_reference is None
        assert request.metadata == {}
        assert request.live is False


class TestOrderResult:
    """Tests for OrderResult dataclass."""

    def test_order_result_creation(self):
        result = OrderResult(
            venue="binance",
            symbol="BTC/USD",
            side=TradeSide.BUY,
            quantity=1.0,
            executed_price=50100.0,
            status="filled",
            venue_order_id="order_123",
            transaction_hash="0xabc",
            metadata={"fee": 10.0},
        )
        assert result.venue == "binance"
        assert result.symbol == "BTC/USD"
        assert result.side == TradeSide.BUY
        assert result.quantity == 1.0
        assert result.executed_price == 50100.0
        assert result.status == "filled"
        assert result.venue_order_id == "order_123"
        assert result.transaction_hash == "0xabc"
        assert result.metadata == {"fee": 10.0}

    def test_order_result_defaults(self):
        result = OrderResult(
            venue="binance",
            symbol="BTC/USD",
            side=TradeSide.BUY,
            quantity=1.0,
            executed_price=50100.0,
            status="filled",
        )
        assert result.venue_order_id is None
        assert result.transaction_hash is None
        assert result.metadata == {}


class TestBalanceSnapshot:
    """Tests for BalanceSnapshot dataclass."""

    def test_balance_snapshot_creation(self):
        snapshot = BalanceSnapshot(
            asset="BTC",
            total=10.0,
            available=8.0,
            usd_value=500000.0,
            metadata={"locked": 2.0},
        )
        assert snapshot.asset == "BTC"
        assert snapshot.total == 10.0
        assert snapshot.available == 8.0
        assert snapshot.usd_value == 500000.0
        assert snapshot.metadata == {"locked": 2.0}

    def test_balance_snapshot_defaults(self):
        snapshot = BalanceSnapshot(
            asset="BTC",
            total=10.0,
            available=8.0,
        )
        assert snapshot.usd_value is None
        assert snapshot.metadata == {}


class TestPositionSnapshot:
    """Tests for PositionSnapshot dataclass."""

    def test_position_snapshot_creation(self):
        snapshot = PositionSnapshot(
            symbol="BTC/USD",
            quantity=1.0,
            entry_price=50000.0,
            mark_price=51000.0,
            unrealized_pnl=1000.0,
            metadata={"leverage": 2},
        )
        assert snapshot.symbol == "BTC/USD"
        assert snapshot.quantity == 1.0
        assert snapshot.entry_price == 50000.0
        assert snapshot.mark_price == 51000.0
        assert snapshot.unrealized_pnl == 1000.0
        assert snapshot.metadata == {"leverage": 2}

    def test_position_snapshot_defaults(self):
        snapshot = PositionSnapshot(
            symbol="BTC/USD",
            quantity=1.0,
            entry_price=50000.0,
            mark_price=51000.0,
            unrealized_pnl=1000.0,
        )
        assert snapshot.metadata == {}


class TestVenueHealth:
    """Tests for VenueHealth dataclass."""

    def test_venue_health_creation(self):
        health = VenueHealth(
            venue="binance",
            status="online",
            last_updated=time.time(),
            latency_ms=50.0,
            last_error=None,
            metadata={"region": "us"},
        )
        assert health.venue == "binance"
        assert health.status == "online"
        assert health.latency_ms == 50.0
        assert health.last_error is None
        assert health.metadata == {"region": "us"}

    def test_venue_health_defaults(self):
        health = VenueHealth(
            venue="binance",
            status="online",
            last_updated=time.time(),
        )
        assert health.latency_ms is None
        assert health.last_error is None
        assert health.metadata == {}


class TestTradingVenueAdapterBase:
    """Tests for TradingVenueAdapterBase class."""

    @pytest.fixture
    def adapter(self):
        with patch.dict(os.environ, {}, clear=True):
            return TradingVenueAdapterBase()

    @pytest.fixture
    def adapter_with_env(self):
        env_vars = {
            "MERID_TEST_API_KEY": "test_key",
            "MERID_TEST_API_SECRET": "test_secret",
            "MERID_TEST_BASE_URL": "https://test.com",
        }
        with patch.dict(os.environ, env_vars, clear=True):
            class TestAdapter(TradingVenueAdapterBase):
                venue = "test"
                supports_trading = True
            return TestAdapter()

    def test_initialization_defaults(self, adapter):
        assert adapter.venue == "venue"
        assert adapter.supported_assets == ()
        assert adapter.supports_trading is False
        assert adapter.api_key is None
        assert adapter.api_secret is None
        assert adapter.base_url is None
        assert adapter.use_mock is True  # No API key = mock mode
        assert adapter._client is None

    def test_initialization_with_env(self, adapter_with_env):
        assert adapter_with_env.api_key == "test_key"
        assert adapter_with_env.api_secret == "test_secret"
        assert adapter_with_env.base_url == "https://test.com"
        assert adapter_with_env.use_mock is False  # Has API key = live mode
        assert adapter_with_env._client is not None

    def test_initialization_explicit_mock(self):
        with patch.dict(os.environ, {}, clear=True):
            adapter = TradingVenueAdapterBase(use_mock=True)
            assert adapter.use_mock is True
            assert adapter._client is None

    def test_initialization_explicit_live(self):
        with patch.dict(os.environ, {}, clear=True):
            adapter = TradingVenueAdapterBase(api_key="key", use_mock=False)
            assert adapter.use_mock is False
            assert adapter._client is not None

    def test_get_health_mock_mode(self, adapter):
        health = adapter.get_health()
        assert health.venue == "venue"
        assert health.status == "offline"
        assert health.metadata["supports_trading"] is False

    def test_get_health_live_mode(self, adapter_with_env):
        health = adapter_with_env.get_health()
        assert health.venue == "test"
        assert health.status == "online"

    def test_get_health_degraded(self, adapter_with_env):
        adapter_with_env._last_error = "Connection timeout"
        health = adapter_with_env.get_health()
        assert health.status == "degraded"
        assert health.last_error == "Connection timeout"

    def test_get_balances_mock_mode(self, adapter):
        balances = adapter.get_balances()
        assert balances == []

    def test_get_balances_live_mode(self, adapter_with_env):
        balances = adapter_with_env.get_balances()
        assert balances == []

    def test_get_positions_mock_mode(self, adapter):
        positions = adapter.get_positions()
        assert positions == []

    def test_get_positions_live_mode(self, adapter_with_env):
        positions = adapter_with_env.get_positions()
        assert positions == []

    def test_submit_order_mock_mode_raises(self, adapter):
        request = TradeRequest(
            venue="venue",
            symbol="BTC/USD",
            side=TradeSide.BUY,
            quantity=1.0,
        )
        with pytest.raises(RuntimeError, match="mock mode"):
            adapter.submit_order(request)

    def test_submit_order_read_only_raises(self, adapter_with_env):
        adapter_with_env.supports_trading = False
        request = TradeRequest(
            venue="test",
            symbol="BTC/USD",
            side=TradeSide.BUY,
            quantity=1.0,
        )
        with pytest.raises(RuntimeError, match="read-only"):
            adapter_with_env.submit_order(request)

    def test_cancel_order_mock_mode(self, adapter):
        result = adapter.cancel_order("order_123")
        assert result is False

    def test_cancel_order_live_mode_not_implemented(self, adapter_with_env):
        with pytest.raises(NotImplementedError):
            adapter_with_env.cancel_order("order_123")

    def test_record_latency(self, adapter):
        start = time.perf_counter()
        time.sleep(0.001)  # Small delay
        adapter._record_latency(start)
        assert adapter._last_latency_ms is not None
        assert adapter._last_latency_ms > 0
        assert adapter._last_error is None

    def test_get_balances_live_hook(self, adapter):
        # Test that _get_balances_live returns empty list by default
        balances = adapter._get_balances_live()
        assert balances == []

    def test_get_positions_live_hook(self, adapter):
        # Test that _get_positions_live returns empty list by default
        positions = adapter._get_positions_live()
        assert positions == []

    def test_submit_order_live_hook(self, adapter):
        # Test that _submit_order_live raises NotImplementedError
        request = TradeRequest(
            venue="venue",
            symbol="BTC/USD",
            side=TradeSide.BUY,
            quantity=1.0,
        )
        with pytest.raises(NotImplementedError):
            adapter._submit_order_live(request)

    def test_cancel_order_live_hook(self, adapter):
        # Test that _cancel_order_live raises NotImplementedError
        with pytest.raises(NotImplementedError):
            adapter._cancel_order_live("order_123")
