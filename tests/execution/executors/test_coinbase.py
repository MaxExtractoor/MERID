"""Comprehensive tests for Coinbase executor - HTTP mocking with respx.

NOTE: CoinbaseExecutor is now aliased to CoinbasePriceFeed (read-only).
Trading, positions, and HMAC signing are disabled by design.
"""

import pytest
import respx
from httpx import Response

from merid.execution.executors.coinbase import CoinbaseExecutor, CoinbasePriceFeed
from merid.execution.base import Quote
from merid.execution.http_base import ExecutionError, NonRetryableError


@pytest.fixture
def executor():
    """Create test Coinbase executor."""
    return CoinbaseExecutor()


class TestCoinbaseExecutorInitialization:
    """Test CoinbaseExecutor initialization."""
    
    def test_initialization(self, executor):
        """Test executor initialization."""
        assert executor.venue == "coinbase_price"
        assert executor.base_url == "https://api.coinbase.com"
        assert executor.default_timeout == 5.0
    
    def test_auth_headers_empty(self, executor):
        """Test auth headers returns empty dict."""
        headers = executor._get_auth_headers()
        assert headers == {}

    def test_is_alias_of_price_feed(self, executor):
        """Test CoinbaseExecutor is an alias for CoinbasePriceFeed."""
        assert isinstance(executor, CoinbasePriceFeed)


class TestCoinbaseExecutorSigning:
    """Test that HMAC signing is not present (read-only feed)."""
    
    def test_sign_not_available(self, executor):
        """CoinbasePriceFeed has no _sign method (read-only)."""
        assert not hasattr(executor, '_sign') or not callable(getattr(executor, '_sign', None))
    
    def test_no_auth_needed_for_price(self, executor):
        """Auth headers are empty for public price endpoints."""
        headers = executor._get_auth_headers()
        assert headers == {}
        assert "CB-ACCESS-KEY" not in headers
        assert "CB-ACCESS-SIGN" not in headers


@respx.mock
class TestCoinbaseExecutorQuotes:
    """Test CoinbaseExecutor quote functionality."""
    
    @pytest.mark.asyncio
    async def test_get_quote_success(self, executor):
        """Test get_quote success via v2 spot endpoint."""
        route = respx.get("https://api.coinbase.com/v2/prices/BTC-USD/spot").mock(
            return_value=Response(200, json={"data": {"amount": "50000.00", "base": "BTC", "currency": "USD"}})
        )
        
        quote = await executor.get_quote("BTC-USD", "buy", 0.5)
        
        assert isinstance(quote, Quote)
        assert quote.symbol == "BTC-USD"
        assert quote.side == "buy"
        assert quote.price == 50000.00
        assert quote.venue == "coinbase_price"
        assert quote.size == 0.5
        assert route.called


class TestCoinbaseExecutorTradingDisabled:
    """Test that trading is hard-disabled on CoinbasePriceFeed."""
    
    @pytest.mark.asyncio
    async def test_execute_trade_raises_non_retryable(self, executor):
        """execute_trade should raise NonRetryableError (read-only feed)."""
        with pytest.raises(NonRetryableError, match="read-only"):
            await executor.execute_trade("BTC-USD", "buy", 0.5)
    
    @pytest.mark.asyncio
    async def test_execute_trade_mentions_kalshi(self, executor):
        """Error message should direct users to Kalshi."""
        with pytest.raises(NonRetryableError) as exc_info:
            await executor.execute_trade("BTC-USD", "buy", 0.5)
        assert "Kalshi" in str(exc_info.value)


class TestCoinbaseExecutorPositionsDisabled:
    """Test that positions are hard-disabled on CoinbasePriceFeed."""
    
    @pytest.mark.asyncio
    async def test_get_positions_raises_non_retryable(self, executor):
        """get_positions should raise NonRetryableError (read-only feed)."""
        with pytest.raises(NonRetryableError, match="does not expose positions"):
            await executor.get_positions()
    
    @pytest.mark.asyncio
    async def test_get_positions_mentions_kalshi(self, executor):
        """Error message should direct users to Kalshi."""
        with pytest.raises(NonRetryableError) as exc_info:
            await executor.get_positions()
        assert "Kalshi" in str(exc_info.value)


class TestCoinbaseExecutorHelpers:
    """Test CoinbaseExecutor helper methods."""
    
    def test_to_product_id_usd(self, executor):
        """Test symbol to product ID conversion with USD."""
        product_id = executor._to_product_id("BTC-USD")
        assert product_id == "BTC-USD"
    
    def test_to_product_id_unsupported(self, executor):
        """Test unsupported symbol raises NonRetryableError."""
        with pytest.raises(NonRetryableError, match="Unsupported"):
            executor._to_product_id("ETH-USD")
    
    def test_to_product_id_other_unsupported(self, executor):
        """Test non-USD pairs are not supported."""
        with pytest.raises(NonRetryableError, match="Unsupported"):
            executor._to_product_id("BTC-EUR")
