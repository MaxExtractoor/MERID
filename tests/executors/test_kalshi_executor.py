"""Tests for KalshiExecutor - Batch 2 Coverage."""
import pytest
import respx
from httpx import Response

from merid.execution.executors.kalshi import KalshiExecutor


@pytest.fixture
def executor():
    """Create a KalshiExecutor instance."""
    return KalshiExecutor()


@pytest.fixture
def mock_kalshi_api():
    """Mock Kalshi API responses."""
    with respx.mock(assert_all_mocked=False) as rsps:
        yield rsps


class TestKalshiExecutor:
    """Tests for Kalshi executor."""

    @pytest.mark.asyncio
    async def test_execute_trade_success(self, executor, mock_kalshi_api):
        """Test successful trade execution."""
        mock_kalshi_api.post("https://api.elections.kalshi.com/trade/v1/order").mock(
            return_value=Response(
                200,
                json={
                    "order_id": "order-456",
                    "executed_price": 0.55,
                    "status": "filled",
                }
            )
        )

        result = await executor.execute_trade(
            symbol="PRES-2024-DEM",
            side="buy",
            amount=100,
        )

        assert result is not None
        assert result.success is True
        assert result.venue == "kalshi"
        assert result.symbol == "PRES-2024-DEM"
        assert result.size == 100
        assert result.tx_id == "order-456"
        assert result.price == 0.55

    @pytest.mark.asyncio
    async def test_execute_trade_connection_error(self, executor, mock_kalshi_api):
        """Test trade execution with connection error."""
        from merid.execution.http_base import ExecutionError
        mock_kalshi_api.post("https://api.elections.kalshi.com/trade/v1/order").mock(
            side_effect=ExecutionError("Network unreachable", "kalshi")
        )

        result = await executor.execute_trade(
            symbol="PRES-2024-DEM",
            side="buy",
            amount=100,
        )

        assert result is not None
        assert result.success is False
        assert "Network unreachable" in result.error

    @pytest.mark.asyncio
    async def test_execute_trade_timeout(self, executor, mock_kalshi_api):
        """Test trade execution with timeout."""
        import asyncio
        mock_kalshi_api.post("https://api.elections.kalshi.com/trade/v1/order").mock(
            side_effect=asyncio.TimeoutError("Request timed out")
        )

        result = await executor.execute_trade(
            symbol="PRES-2024-DEM",
            side="buy",
            amount=100,
        )

        assert result is not None
        assert result.success is False

    @pytest.mark.asyncio
    async def test_get_quote_success(self, executor, mock_kalshi_api):
        """Test getting a quote."""
        mock_kalshi_api.get("https://api.elections.kalshi.com/trade/v1/price").mock(
            return_value=Response(200, json={"price": 0.52})
        )

        quote = await executor.get_quote(
            symbol="PRES-2024-DEM",
            side="buy",
            amount=100,
        )

        assert quote is not None
        assert quote.symbol == "PRES-2024-DEM"
        assert quote.price == 0.52
        assert quote.venue == "kalshi"

    @pytest.mark.asyncio
    async def test_get_positions_success(self, executor, mock_kalshi_api):
        """Test fetching positions."""
        mock_kalshi_api.get("https://api.elections.kalshi.com/portfolio/v1/positions").mock(
            return_value=Response(
                200,
                json={
                    "positions": [
                        {
                            "ticker": "PRES-2024-DEM",
                            "count": 100,
                            "avg_price": 0.50,
                            "pnl": 5.0,
                        },
                        {
                            "ticker": "PRES-2024-REP",
                            "count": 50,
                            "avg_price": 0.48,
                            "pnl": -2.0,
                        },
                    ]
                }
            )
        )

        positions = await executor.get_positions()

        assert len(positions) == 2
        assert positions[0].symbol == "PRES-2024-DEM"
        assert positions[0].size == 100
        assert positions[0].entry_price == 0.50
        assert positions[0].pnl == 5.0

    @pytest.mark.asyncio
    async def test_get_positions_empty(self, executor, mock_kalshi_api):
        """Test fetching positions with no open positions."""
        mock_kalshi_api.get("https://api.elections.kalshi.com/portfolio/v1/positions").mock(
            return_value=Response(200, json={"positions": []})
        )

        positions = await executor.get_positions()

        assert len(positions) == 0

    def test_symbol_to_ticker_mapping(self, executor):
        """Test symbol to ticker conversion."""
        assert executor._symbol_to_ticker("PRES-2024-DEM") == "PRES-2024-DEM"
        assert executor._symbol_to_ticker("PRES-2024-REP") == "PRES-2024-REP"
        assert executor._symbol_to_ticker("UNKNOWN") == "UNKNOWN"

    def test_ticker_to_symbol_mapping(self, executor):
        """Test ticker to symbol conversion."""
        assert executor._ticker_to_symbol("PRES-2024-DEM") == "PRES-2024-DEM"
        assert executor._ticker_to_symbol("PRES-2024-REP") == "PRES-2024-REP"
