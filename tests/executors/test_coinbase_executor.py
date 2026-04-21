"""Tests for CoinbaseExecutor - Batch 2 Coverage."""
import pytest
import respx
from httpx import Response

from merid.execution.executors.coinbase import CoinbaseExecutor
from merid.execution.base import TradeResult


@pytest.fixture
def executor():
    """Create a CoinbaseExecutor instance."""
    return CoinbaseExecutor()


@pytest.fixture
def mock_coinbase_api():
    """Mock Coinbase API responses."""
    with respx.mock(assert_all_mocked=False) as rsps:
        yield rsps


class TestCoinbaseExecutor:
    """Tests for Coinbase executor."""

    @pytest.mark.asyncio
    async def test_execute_trade_success(self, executor, mock_coinbase_api):
        """Test successful trade execution."""
        mock_coinbase_api.post("https://api.coinbase.com/v2/orders").mock(
            return_value=Response(
                200,
                json={
                    "id": "order-123",
                    "executed_value": "4500.00",
                    "size": "0.1",
                    "side": "buy",
                }
            )
        )

        result = await executor.execute_trade(
            symbol="BTC-USD",
            side="buy",
            amount=0.1,
        )

        assert result is not None
        assert result.success is True
        assert result.venue == "coinbase"
        assert result.symbol == "BTC-USD"
        assert result.size == 0.1
        assert result.tx_id == "order-123"

    @pytest.mark.asyncio
    async def test_execute_trade_connection_error(self, executor, mock_coinbase_api):
        """Test trade execution with connection error."""
        from merid.execution.http_base import ExecutionError
        mock_coinbase_api.post("https://api.coinbase.com/v2/orders").mock(
            side_effect=ExecutionError("Connection refused", "coinbase")
        )

        result = await executor.execute_trade(
            symbol="BTC-USD",
            side="buy",
            amount=0.1,
        )

        assert result is not None
        assert result.success is False
        assert "Connection refused" in result.error

    @pytest.mark.asyncio
    async def test_execute_trade_timeout(self, executor, mock_coinbase_api):
        """Test trade execution with timeout."""
        import asyncio
        mock_coinbase_api.post("https://api.coinbase.com/v2/orders").mock(
            side_effect=asyncio.TimeoutError("Request timed out")
        )

        result = await executor.execute_trade(
            symbol="BTC-USD",
            side="buy",
            amount=0.1,
        )

        assert result is not None
        assert result.success is False
        assert "timed out" in result.error.lower() or "API error" in result.error

    @pytest.mark.asyncio
    async def test_get_quote_success(self, executor, mock_coinbase_api):
        """Test getting a quote."""
        mock_coinbase_api.get("https://api.coinbase.com/v2/products/BTC-USD/ticker").mock(
            return_value=Response(200, json={"price": "45000.00"})
        )

        quote = await executor.get_quote(
            symbol="BTC-USD",
            side="buy",
            amount=0.1,
        )

        assert quote is not None
        assert quote.symbol == "BTC-USD"
        assert quote.price == 45000.0
        assert quote.venue == "coinbase"

    @pytest.mark.asyncio
    async def test_get_positions_success(self, executor, mock_coinbase_api):
        """Test fetching positions."""
        mock_coinbase_api.get("https://api.coinbase.com/v2/accounts").mock(
            return_value=Response(
                200,
                json={
                    "data": [
                        {
                            "id": "acc-1",
                            "currency": "BTC",
                            "type": "wallet",
                            "available": {"value": "0.5"},
                        },
                        {
                            "id": "acc-2",
                            "currency": "ETH",
                            "type": "wallet",
                            "available": {"value": "2.0"},
                        },
                    ]
                }
            )
        )

        positions = await executor.get_positions()

        assert len(positions) == 2
        assert positions[0].symbol == "BTC-USD"
        assert positions[0].size == 0.5
        assert positions[1].symbol == "ETH-USD"

    @pytest.mark.asyncio
    async def test_get_positions_empty(self, executor, mock_coinbase_api):
        """Test fetching positions with no balances."""
        mock_coinbase_api.get("https://api.coinbase.com/v2/accounts").mock(
            return_value=Response(200, json={"data": []})
        )

        positions = await executor.get_positions()

        assert len(positions) == 0

    def test_to_product_id(self, executor):
        """Test symbol to product ID conversion."""
        assert executor._to_product_id("BTC-USD") == "BTC-USD"
        assert executor._to_product_id("BTC-USD") == "BTC-USD"
        assert executor._to_product_id("ETH-USD") == "ETH-USD"
