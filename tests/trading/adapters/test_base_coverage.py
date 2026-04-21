"""Comprehensive tests for trading/adapters/base.py - Coverage improvement."""

import pytest
import time
from unittest.mock import MagicMock, patch

from trading.adapters.base import (
    TradeSide, OrderType, TradeRequest, OrderResult,
    BalanceSnapshot, PositionSnapshot, VenueHealth,
    TradingVenueAdapterBase
)


# =============================================================================
# Enum Tests
# =============================================================================

class TestTradeSide:
    """Test TradeSide enum."""

    def test_buy_value(self):
        assert TradeSide.BUY.value == "buy"

    def test_sell_value(self):
        assert TradeSide.SELL.value == "sell"

    def test_is_string_enum(self):
        assert isinstance(TradeSide.BUY, str)
        assert TradeSide.BUY == "buy"


class TestOrderType:
    """Test OrderType enum."""

    def test_market_value(self):
        assert OrderType.MARKET.value == "market"

    def test_limit_value(self):
        assert OrderType.LIMIT.value == "limit"

    def test_ioc_value(self):
        assert OrderType.IOC.value == "ioc"

    def test_fok_value(self):
        assert OrderType.FOK.value == "fok"


# =============================================================================
# Dataclass Tests
# =============================================================================

class TestTradeRequest:
    """Test TradeRequest dataclass."""

    def test_minimal_creation(self):
        request = TradeRequest(
            venue="binance",
            symbol="BTC/USD",
            side=TradeSide.BUY,
            quantity=1.0
        )
        assert request.venue == "binance"
        assert request.order_type == OrderType.MARKET
        assert request.live is False

    def test_full_creation(self):
        request = TradeRequest(
            venue="alpaca",
            symbol="AAPL",
            side=TradeSide.SELL,
            quantity=100.0,
            order_type=OrderType.LIMIT,
            price=150.0,
            notional_usd=15000.0,
            client_reference="ref_123",
            metadata={"strategy": "momentum"},
            live=True
        )
        assert request.order_type == OrderType.LIMIT
        assert request.price == 150.0
        assert request.live is True

    def test_is_frozen(self):
        request = TradeRequest(
            venue="test",
            symbol="TEST",
            side=TradeSide.BUY,
            quantity=1.0
        )
        with pytest.raises(AttributeError):
            request.quantity = 2.0


class TestOrderResult:
    """Test OrderResult dataclass."""

    def test_creation(self):
        result = OrderResult(
            venue="binance",
            symbol="BTC/USD",
            side=TradeSide.BUY,
            quantity=1.0,
            executed_price=50000.0,
            status="filled"
        )
        assert result.venue == "binance"
        assert result.status == "filled"
        assert result.venue_order_id is None

    def test_with_optional_fields(self):
        result = OrderResult(
            venue="binance",
            symbol="BTC/USD",
            side=TradeSide.BUY,
            quantity=1.0,
            executed_price=50000.0,
            status="filled",
            venue_order_id="order_123",
            transaction_hash="0xabc123",
            metadata={"fee": 0.1}
        )
        assert result.venue_order_id == "order_123"
        assert result.transaction_hash == "0xabc123"


class TestBalanceSnapshot:
    """Test BalanceSnapshot dataclass."""

    def test_creation(self):
        balance = BalanceSnapshot(
            asset="BTC",
            total=1.5,
            available=1.0
        )
        assert balance.asset == "BTC"
        assert balance.usd_value is None

    def test_with_usd_value(self):
        balance = BalanceSnapshot(
            asset="BTC",
            total=1.5,
            available=1.0,
            usd_value=75000.0
        )
        assert balance.usd_value == 75000.0


class TestPositionSnapshot:
    """Test PositionSnapshot dataclass."""

    def test_creation(self):
        position = PositionSnapshot(
            symbol="BTC/USD",
            quantity=0.5,
            entry_price=48000.0,
            mark_price=50000.0,
            unrealized_pnl=1000.0
        )
        assert position.symbol == "BTC/USD"
        assert position.unrealized_pnl == 1000.0


class TestVenueHealth:
    """Test VenueHealth dataclass."""

    def test_creation(self):
        health = VenueHealth(
            venue="binance",
            status="online",
            last_updated=time.time()
        )
        assert health.venue == "binance"
        assert health.latency_ms is None

    def test_with_optional_fields(self):
        health = VenueHealth(
            venue="binance",
            status="degraded",
            last_updated=time.time(),
            latency_ms=50.5,
            last_error="Connection timeout"
        )
        assert health.latency_ms == 50.5
        assert health.last_error == "Connection timeout"


# =============================================================================
# TradingVenueAdapterBase Tests
# =============================================================================

class TestTradingVenueAdapterBaseInit:
    """Test TradingVenueAdapterBase initialization."""

    def test_init_defaults(self, monkeypatch):
        monkeypatch.delenv("MERID_VENUE_API_KEY", raising=False)
        monkeypatch.delenv("MERID_VENUE_API_SECRET", raising=False)
        monkeypatch.delenv("MERID_VENUE_BASE_URL", raising=False)
        
        adapter = TradingVenueAdapterBase()
        
        assert adapter.api_key is None
        assert adapter.use_mock is True  # No API key = mock mode

    def test_init_with_credentials(self):
        adapter = TradingVenueAdapterBase(
            api_key="test_key",
            api_secret="test_secret",
            base_url="https://api.test.com"
        )
        
        assert adapter.api_key == "test_key"
        assert adapter.api_secret == "test_secret"
        assert adapter.base_url == "https://api.test.com"
        assert adapter.use_mock is False

    def test_init_from_env(self, monkeypatch):
        monkeypatch.setenv("MERID_VENUE_API_KEY", "env_key")
        monkeypatch.setenv("MERID_VENUE_API_SECRET", "env_secret")
        monkeypatch.setenv("MERID_VENUE_BASE_URL", "https://env.api.com")
        
        adapter = TradingVenueAdapterBase()
        
        assert adapter.api_key == "env_key"
        assert adapter.use_mock is False

    def test_init_explicit_mock(self):
        adapter = TradingVenueAdapterBase(
            api_key="test_key",
            use_mock=True
        )
        
        assert adapter.use_mock is True
        assert adapter._client is None


class TestGetHealth:
    """Test get_health method."""

    def test_health_mock_mode(self, monkeypatch):
        monkeypatch.delenv("MERID_VENUE_API_KEY", raising=False)
        
        adapter = TradingVenueAdapterBase()
        health = adapter.get_health()
        
        assert health.status == "offline"
        assert health.venue == "venue"

    def test_health_live_mode(self):
        adapter = TradingVenueAdapterBase(api_key="key", use_mock=False)
        health = adapter.get_health()
        
        assert health.status == "online"

    def test_health_degraded(self):
        adapter = TradingVenueAdapterBase(api_key="key", use_mock=False)
        adapter._last_error = "Connection failed"
        health = adapter.get_health()
        
        assert health.status == "degraded"
        assert health.last_error == "Connection failed"

    def test_health_includes_latency(self):
        adapter = TradingVenueAdapterBase(api_key="key", use_mock=False)
        adapter._last_latency_ms = 45.5
        health = adapter.get_health()
        
        assert health.latency_ms == 45.5


class TestGetBalances:
    """Test get_balances method."""

    def test_balances_mock_mode(self, monkeypatch):
        monkeypatch.delenv("MERID_VENUE_API_KEY", raising=False)
        
        adapter = TradingVenueAdapterBase()
        balances = adapter.get_balances()
        
        assert balances == []

    def test_balances_live_mode(self):
        adapter = TradingVenueAdapterBase(api_key="key", use_mock=False)
        
        # Default implementation returns empty list
        balances = adapter.get_balances()
        assert balances == []


class TestGetPositions:
    """Test get_positions method."""

    def test_positions_mock_mode(self, monkeypatch):
        monkeypatch.delenv("MERID_VENUE_API_KEY", raising=False)
        
        adapter = TradingVenueAdapterBase()
        positions = adapter.get_positions()
        
        assert positions == []

    def test_positions_live_mode(self):
        adapter = TradingVenueAdapterBase(api_key="key", use_mock=False)
        
        # Default implementation returns empty list
        positions = adapter.get_positions()
        assert positions == []


class TestSubmitOrder:
    """Test submit_order method."""

    def test_submit_mock_mode_raises(self, monkeypatch):
        monkeypatch.delenv("MERID_VENUE_API_KEY", raising=False)
        
        adapter = TradingVenueAdapterBase()
        request = TradeRequest(
            venue="test",
            symbol="BTC/USD",
            side=TradeSide.BUY,
            quantity=1.0
        )
        
        with pytest.raises(RuntimeError, match="mock mode"):
            adapter.submit_order(request)

    def test_submit_readonly_raises(self):
        adapter = TradingVenueAdapterBase(api_key="key", use_mock=False)
        adapter.supports_trading = False
        
        request = TradeRequest(
            venue="test",
            symbol="BTC/USD",
            side=TradeSide.BUY,
            quantity=1.0
        )
        
        with pytest.raises(RuntimeError, match="read-only"):
            adapter.submit_order(request)

    def test_submit_not_implemented(self):
        adapter = TradingVenueAdapterBase(api_key="key", use_mock=False)
        adapter.supports_trading = True
        
        request = TradeRequest(
            venue="test",
            symbol="BTC/USD",
            side=TradeSide.BUY,
            quantity=1.0
        )
        
        with pytest.raises(NotImplementedError):
            adapter.submit_order(request)


class TestCancelOrder:
    """Test cancel_order method."""

    def test_cancel_mock_mode(self, monkeypatch):
        monkeypatch.delenv("MERID_VENUE_API_KEY", raising=False)
        
        adapter = TradingVenueAdapterBase()
        result = adapter.cancel_order("order_123")
        
        assert result is False

    def test_cancel_not_implemented(self):
        adapter = TradingVenueAdapterBase(api_key="key", use_mock=False)
        
        with pytest.raises(NotImplementedError):
            adapter.cancel_order("order_123")


class TestRecordLatency:
    """Test _record_latency method."""

    def test_records_latency(self):
        adapter = TradingVenueAdapterBase(api_key="key", use_mock=False)
        adapter._last_error = "Previous error"
        
        start = time.perf_counter() - 0.05  # 50ms ago
        adapter._record_latency(start)
        
        assert adapter._last_latency_ms >= 50.0
        assert adapter._last_error is None  # Cleared on success


class TestSubclassHooks:
    """Test default subclass hook implementations."""

    def test_get_balances_live_default(self):
        adapter = TradingVenueAdapterBase(api_key="key", use_mock=False)
        result = adapter._get_balances_live()
        assert result == []

    def test_get_positions_live_default(self):
        adapter = TradingVenueAdapterBase(api_key="key", use_mock=False)
        result = adapter._get_positions_live()
        assert result == []

    def test_submit_order_live_not_implemented(self):
        adapter = TradingVenueAdapterBase(api_key="key", use_mock=False)
        request = TradeRequest(
            venue="test",
            symbol="BTC",
            side=TradeSide.BUY,
            quantity=1.0
        )
        with pytest.raises(NotImplementedError):
            adapter._submit_order_live(request)

    def test_cancel_order_live_not_implemented(self):
        adapter = TradingVenueAdapterBase(api_key="key", use_mock=False)
        with pytest.raises(NotImplementedError):
            adapter._cancel_order_live("order_123")
