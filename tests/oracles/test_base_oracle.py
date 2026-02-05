"""Tests for oracles/base_oracle.py."""
import pytest
import time
from unittest.mock import Mock, patch, AsyncMock
from oracles.base_oracle import (
    OracleStatus, OraclePrice, OracleHealth, BaseOracle
)


class TestOracleStatus:
    """Test OracleStatus enum."""

    def test_oracle_status_values(self):
        """Test oracle status enum values."""
        assert OracleStatus.DISCONNECTED.value == "disconnected"
        assert OracleStatus.CONNECTING.value == "connecting"
        assert OracleStatus.CONNECTED.value == "connected"
        assert OracleStatus.DEGRADED.value == "degraded"
        assert OracleStatus.ERROR.value == "error"


class TestOraclePrice:
    """Test OraclePrice dataclass."""

    def test_creation(self):
        """Test OraclePrice creation."""
        price = OraclePrice(
            oracle_id="coingecko",
            symbol="BTC/USD",
            price=50000.0,
            timestamp=1234567890.0,
            confidence=0.95
        )
        assert price.oracle_id == "coingecko"
        assert price.symbol == "BTC/USD"
        assert price.price == 50000.0
        assert price.confidence == 0.95

    def test_age_seconds(self):
        """Test age_seconds method."""
        now = time.time()
        price = OraclePrice(
            oracle_id="coingecko",
            symbol="BTC/USD",
            price=50000.0,
            timestamp=now - 30.0  # 30 seconds ago
        )
        age = price.age_seconds()
        assert 29.0 <= age <= 31.0  # Allow for execution time

    def test_is_stale(self):
        """Test is_stale method."""
        now = time.time()
        
        # Fresh price
        fresh_price = OraclePrice(
            oracle_id="coingecko",
            symbol="BTC/USD",
            price=50000.0,
            timestamp=now
        )
        assert fresh_price.is_stale() is False
        assert fresh_price.is_stale(max_age_seconds=30.0) is False
        
        # Stale price
        stale_price = OraclePrice(
            oracle_id="coingecko",
            symbol="BTC/USD",
            price=50000.0,
            timestamp=now - 120.0  # 2 minutes ago
        )
        assert stale_price.is_stale() is True


class TestOracleHealth:
    """Test OracleHealth dataclass."""

    def test_creation(self):
        """Test OracleHealth creation."""
        health = OracleHealth(
            oracle_id="coingecko",
            status=OracleStatus.CONNECTED,
            last_update=1234567890.0,
            request_count=100,
            error_count=5,
            avg_latency_ms=150.0,
            uptime_seconds=3600.0
        )
        assert health.oracle_id == "coingecko"
        assert health.status == OracleStatus.CONNECTED
        assert health.is_healthy() is True

    def test_is_healthy_not_connected(self):
        """Test is_healthy when not connected."""
        health = OracleHealth(
            oracle_id="coingecko",
            status=OracleStatus.ERROR,
            last_update=1234567890.0,
            request_count=0,
            error_count=0,
            avg_latency_ms=0.0,
            uptime_seconds=0.0
        )
        assert health.is_healthy() is False


class TestBaseOracle:
    """Test BaseOracle abstract class."""

    def test_initialization(self):
        """Test oracle initialization."""
        class TestOracle(BaseOracle):
            async def _connect_impl(self): return True
            async def _disconnect_impl(self): pass
            async def _fetch_price_impl(self, symbol): return None

        oracle = TestOracle("test_oracle", priority=2)
        
        assert oracle.oracle_id == "test_oracle"
        assert oracle.priority == 2
        assert oracle.status == OracleStatus.DISCONNECTED

    def test_get_health(self):
        """Test get_health method."""
        class TestOracle(BaseOracle):
            async def _connect_impl(self): return True
            async def _disconnect_impl(self): pass
            async def _fetch_price_impl(self, symbol): return None

        oracle = TestOracle("test_oracle")
        health = oracle.get_health()
        
        assert health.oracle_id == "test_oracle"
        assert health.status == OracleStatus.DISCONNECTED
        assert health.request_count == 0

    def test_get_cached_price_fresh(self):
        """Test get_cached_price with fresh cache."""
        class TestOracle(BaseOracle):
            async def _connect_impl(self): return True
            async def _disconnect_impl(self): pass
            async def _fetch_price_impl(self, symbol): return None

        oracle = TestOracle("test_oracle")
        
        # Add fresh cache entry
        fresh_price = OraclePrice(
            oracle_id="test_oracle",
            symbol="BTC/USD",
            price=50000.0,
            timestamp=time.time()
        )
        oracle._price_cache["BTC/USD"] = fresh_price
        
        cached = oracle.get_cached_price("BTC/USD")
        assert cached == fresh_price

    def test_get_cached_price_stale(self):
        """Test get_cached_price with stale cache."""
        class TestOracle(BaseOracle):
            async def _connect_impl(self): return True
            async def _disconnect_impl(self): pass
            async def _fetch_price_impl(self, symbol): return None

        oracle = TestOracle("test_oracle")
        
        # Add stale cache entry
        stale_price = OraclePrice(
            oracle_id="test_oracle",
            symbol="BTC/USD",
            price=50000.0,
            timestamp=time.time() - 120.0  # 2 minutes old
        )
        oracle._price_cache["BTC/USD"] = stale_price
        
        cached = oracle.get_cached_price("BTC/USD")
        assert cached is None

    @pytest.mark.asyncio
    async def test_connect_success(self):
        """Test successful connection."""
        class TestOracle(BaseOracle):
            async def _connect_impl(self): return True
            async def _disconnect_impl(self): pass
            async def _fetch_price_impl(self, symbol): return None

        oracle = TestOracle("test_oracle")
        success = await oracle.connect()
        
        assert success is True
        assert oracle.status == OracleStatus.CONNECTED

    @pytest.mark.asyncio
    async def test_connect_failure(self):
        """Test failed connection."""
        class TestOracle(BaseOracle):
            async def _connect_impl(self): return False
            async def _disconnect_impl(self): pass
            async def _fetch_price_impl(self, symbol): return None

        oracle = TestOracle("test_oracle")
        success = await oracle.connect()
        
        assert success is False
        assert oracle.status == OracleStatus.ERROR

    @pytest.mark.asyncio
    async def test_connect_exception(self):
        """Test connection with exception."""
        class TestOracle(BaseOracle):
            async def _connect_impl(self): raise Exception("Connection error")
            async def _disconnect_impl(self): pass
            async def _fetch_price_impl(self, symbol): return None

        oracle = TestOracle("test_oracle")
        success = await oracle.connect()
        
        assert success is False
        assert oracle.status == OracleStatus.ERROR
        assert oracle._error_count == 1

    @pytest.mark.asyncio
    async def test_disconnect(self):
        """Test disconnect."""
        class TestOracle(BaseOracle):
            async def _connect_impl(self): return True
            async def _disconnect_impl(self): pass
            async def _fetch_price_impl(self, symbol): return None

        oracle = TestOracle("test_oracle")
        oracle._status = OracleStatus.CONNECTED
        
        await oracle.disconnect()
        
        assert oracle.status == OracleStatus.DISCONNECTED

    @pytest.mark.asyncio
    async def test_get_price_from_cache(self):
        """Test get_price returns cached value."""
        class TestOracle(BaseOracle):
            async def _connect_impl(self): return True
            async def _disconnect_impl(self): pass
            async def _fetch_price_impl(self, symbol): return None

        oracle = TestOracle("test_oracle")
        
        # Add fresh cache entry
        fresh_price = OraclePrice(
            oracle_id="test_oracle",
            symbol="BTC/USD",
            price=50000.0,
            timestamp=time.time()
        )
        oracle._price_cache["BTC/USD"] = fresh_price
        
        price = await oracle.get_price("BTC/USD")
        assert price == fresh_price

    @pytest.mark.asyncio
    async def test_get_price_fetch(self):
        """Test get_price fetches when not cached."""
        fetched_price = OraclePrice(
            oracle_id="test_oracle",
            symbol="ETH/USD",
            price=3000.0,
            timestamp=time.time()
        )
        
        class TestOracle(BaseOracle):
            async def _connect_impl(self): return True
            async def _disconnect_impl(self): pass
            async def _fetch_price_impl(self, symbol): return fetched_price

        oracle = TestOracle("test_oracle")
        price = await oracle.get_price("ETH/USD")
        
        assert price == fetched_price
        assert oracle._request_count == 1
        assert "ETH/USD" in oracle._price_cache

    @pytest.mark.asyncio
    async def test_get_price_exception(self):
        """Test get_price handles exception."""
        class TestOracle(BaseOracle):
            async def _connect_impl(self): return True
            async def _disconnect_impl(self): pass
            async def _fetch_price_impl(self, symbol): raise Exception("Fetch error")

        oracle = TestOracle("test_oracle")
        price = await oracle.get_price("BTC/USD")
        
        assert price is None
        assert oracle._error_count == 1

    @pytest.mark.asyncio
    async def test_get_prices(self):
        """Test get_prices for multiple symbols."""
        btc_price = OraclePrice(
            oracle_id="test_oracle",
            symbol="BTC/USD",
            price=50000.0,
            timestamp=time.time()
        )
        eth_price = OraclePrice(
            oracle_id="test_oracle",
            symbol="ETH/USD",
            price=3000.0,
            timestamp=time.time()
        )
        
        prices_map = {
            "BTC/USD": btc_price,
            "ETH/USD": eth_price
        }
        
        class TestOracle(BaseOracle):
            async def _connect_impl(self): return True
            async def _disconnect_impl(self): pass
            async def _fetch_price_impl(self, symbol): return prices_map.get(symbol)

        oracle = TestOracle("test_oracle")
        prices = await oracle.get_prices(["BTC/USD", "ETH/USD"])
        
        assert len(prices) == 2
        assert prices["BTC/USD"].price == 50000.0
        assert prices["ETH/USD"].price == 3000.0
