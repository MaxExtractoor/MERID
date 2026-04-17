"""Tests for CoinbasePriceFeed (read-only price adapter)."""

import pytest
import respx
from httpx import Response

from merid.execution.executors.coinbase import CoinbasePriceFeed, CoinbaseExecutor
from merid.execution.base import Quote
from merid.execution.http_base import ExecutionError, NonRetryableError


class TestCoinbasePriceFeedInitialization:
    """Test CoinbasePriceFeed initialization."""

    def test_default_initialization(self):
        """Test initialization with default values."""
        feed = CoinbasePriceFeed()
        assert feed.venue == "coinbase_price"
        assert feed.base_url == "https://api.coinbase.com"
        assert feed.default_timeout == 5.0

    def test_supported_products(self):
        """Test supported products list."""
        feed = CoinbasePriceFeed()
        assert "BTC-USD" in feed.SUPPORTED_PRODUCTS
        assert "ETH-USD" in feed.SUPPORTED_PRODUCTS
        assert "SOL-USD" in feed.SUPPORTED_PRODUCTS
        assert "XRP-USD" in feed.SUPPORTED_PRODUCTS
        assert "DOGE-USD" in feed.SUPPORTED_PRODUCTS

    def test_backward_compatibility_alias(self):
        """Test CoinbaseExecutor is an alias for CoinbasePriceFeed."""
        executor = CoinbaseExecutor()
        assert isinstance(executor, CoinbasePriceFeed)
        assert executor.venue == "coinbase_price"


class TestCoinbasePriceFeedProductId:
    """Test _to_product_id conversion."""

    def test_supported_symbols(self):
        """Test conversion for supported symbols."""
        feed = CoinbasePriceFeed()
        
        assert feed._to_product_id("BTC-USD") == "BTC-USD"
        assert feed._to_product_id("btc-usd") == "BTC-USD"  # case insensitive
        assert feed._to_product_id("ETH-USD") == "ETH-USD"

    def test_unsupported_symbol_raises_error(self):
        """Test unsupported symbols raise NonRetryableError."""
        feed = CoinbasePriceFeed()
        
        with pytest.raises(NonRetryableError, match="Unsupported Coinbase price symbol"):
            feed._to_product_id("INVALID-USD")
        
        with pytest.raises(NonRetryableError, match="Unsupported Coinbase price symbol"):
            feed._to_product_id("ABC-XYZ")


class TestCoinbasePriceFeedGetPrice:
    """Test get_price method."""

    @respx.mock
    @pytest.mark.asyncio
    async def test_get_price_success(self):
        """Test successful price retrieval."""
        feed = CoinbasePriceFeed()
        
        route = respx.get("https://api.coinbase.com/v2/prices/BTC-USD/spot").mock(
            return_value=Response(200, json={"data": {"amount": "45000.00", "base": "BTC", "currency": "USD"}})
        )
        
        price = await feed.get_price("BTC-USD")
        
        assert price == 45000.00
        assert route.called

    @respx.mock
    @pytest.mark.asyncio
    async def test_get_price_eth(self):
        """Test successful ETH price retrieval."""
        feed = CoinbasePriceFeed()
        
        route = respx.get("https://api.coinbase.com/v2/prices/ETH-USD/spot").mock(
            return_value=Response(200, json={"data": {"amount": "3000.50", "base": "ETH", "currency": "USD"}})
        )
        
        price = await feed.get_price("ETH-USD")
        
        assert price == 3000.50
        assert route.called

    @respx.mock
    @pytest.mark.asyncio
    async def test_get_price_missing_price_field(self):
        """Test handling missing price field."""
        feed = CoinbasePriceFeed()
        
        # v2 returns no amount, Exchange ticker also mocked empty
        respx.get("https://api.coinbase.com/v2/prices/BTC-USD/spot").mock(
            return_value=Response(200, json={"data": {"other_field": "value"}})
        )
        respx.get("https://api.exchange.coinbase.com/products/BTC-USD/ticker").mock(
            return_value=Response(200, json={"other_field": "value"})
        )
        
        with pytest.raises(ExecutionError, match="No price returned"):
            await feed.get_price("BTC-USD")

    @respx.mock
    @pytest.mark.asyncio
    async def test_get_price_api_error(self):
        """Test handling API error."""
        feed = CoinbasePriceFeed()
        
        # Both v2 and Exchange ticker fail
        respx.get("https://api.coinbase.com/v2/prices/BTC-USD/spot").mock(
            return_value=Response(500, json={"error": "Internal server error"})
        )
        respx.get("https://api.exchange.coinbase.com/products/BTC-USD/ticker").mock(
            return_value=Response(500, json={"error": "Internal server error"})
        )
        
        with pytest.raises(ExecutionError):
            await feed.get_price("BTC-USD")

    @pytest.mark.asyncio
    async def test_get_price_unsupported_symbol(self):
        """Test unsupported symbol raises error."""
        feed = CoinbasePriceFeed()
        
        with pytest.raises(NonRetryableError, match="Unsupported Coinbase price symbol"):
            await feed.get_price("INVALID-USD")


class TestCoinbasePriceFeedGetQuote:
    """Test get_quote method."""

    @respx.mock
    @pytest.mark.asyncio
    async def test_get_quote_success(self):
        """Test successful quote retrieval."""
        feed = CoinbasePriceFeed()
        
        route = respx.get("https://api.coinbase.com/v2/prices/BTC-USD/spot").mock(
            return_value=Response(200, json={"data": {"amount": "45000.00", "base": "BTC", "currency": "USD"}})
        )
        
        quote = await feed.get_quote("BTC-USD", "buy", 1.0)
        
        assert isinstance(quote, Quote)
        assert quote.symbol == "BTC-USD"
        assert quote.side == "buy"
        assert quote.price == 45000.00
        assert quote.venue == "coinbase_price"
        assert quote.size == 1.0
        assert quote.metadata["source"] == "coinbase_product_price"
        assert route.called

    @respx.mock
    @pytest.mark.asyncio
    async def test_get_quote_sell_side(self):
        """Test getting quote for sell side."""
        feed = CoinbasePriceFeed()
        
        route = respx.get("https://api.coinbase.com/v2/prices/ETH-USD/spot").mock(
            return_value=Response(200, json={"data": {"amount": "3000.00", "base": "ETH", "currency": "USD"}})
        )
        
        quote = await feed.get_quote("ETH-USD", "sell", 5.0)
        
        assert quote.side == "sell"
        assert quote.price == 3000.00
        assert route.called

    @respx.mock
    @pytest.mark.asyncio
    async def test_get_quote_ignores_side_and_amount_for_price(self):
        """Test that side and amount don't affect price (spot feed)."""
        feed = CoinbasePriceFeed()
        
        route = respx.get("https://api.coinbase.com/v2/prices/BTC-USD/spot").mock(
            return_value=Response(200, json={"data": {"amount": "45000.00", "base": "BTC", "currency": "USD"}})
        )
        
        # Same symbol, different side/amount should return same price
        quote_buy = await feed.get_quote("BTC-USD", "buy", 1.0)
        quote_sell = await feed.get_quote("BTC-USD", "sell", 100.0)
        
        assert quote_buy.price == quote_sell.price == 45000.00


class TestCoinbasePriceFeedTradingDisabled:
    """Test that trading methods are hard-disabled."""

    @pytest.mark.asyncio
    async def test_execute_trade_raises_error(self):
        """Test execute_trade raises NonRetryableError."""
        feed = CoinbasePriceFeed()
        
        with pytest.raises(NonRetryableError, match="read-only"):
            await feed.execute_trade("BTC-USD", "buy", 1.0)

    @pytest.mark.asyncio
    async def test_execute_trade_error_message(self):
        """Test execute_trade error message mentions Kalshi."""
        feed = CoinbasePriceFeed()
        
        with pytest.raises(NonRetryableError) as exc_info:
            await feed.execute_trade("BTC-USD", "buy", 1.0, order_type="market")
        
        error_msg = str(exc_info.value)
        assert "read-only" in error_msg
        assert "trading is disabled" in error_msg
        assert "Kalshi" in error_msg

    @pytest.mark.asyncio
    async def test_get_positions_raises_error(self):
        """Test get_positions raises NonRetryableError."""
        feed = CoinbasePriceFeed()
        
        with pytest.raises(NonRetryableError, match="does not expose positions"):
            await feed.get_positions()

    @pytest.mark.asyncio
    async def test_get_positions_error_message(self):
        """Test get_positions error message."""
        feed = CoinbasePriceFeed()
        
        with pytest.raises(NonRetryableError) as exc_info:
            await feed.get_positions()
        
        error_msg = str(exc_info.value)
        assert "does not expose positions" in error_msg
        assert "Kalshi" in error_msg


class TestCoinbasePriceFeedNoAuth:
    """Test that no authentication is required."""

    @respx.mock
    @pytest.mark.asyncio
    async def test_get_price_no_auth_headers(self):
        """Test price endpoint works without auth headers."""
        feed = CoinbasePriceFeed()
        
        route = respx.get("https://api.coinbase.com/v2/prices/BTC-USD/spot").mock(
            return_value=Response(200, json={"data": {"amount": "45000.00", "base": "BTC", "currency": "USD"}})
        )
        
        price = await feed.get_price("BTC-USD")
        
        assert price == 45000.00
        # Verify no auth headers were sent
        request = route.calls[0].request
        assert "CB-ACCESS-KEY" not in request.headers
        assert "CB-ACCESS-SIGN" not in request.headers
