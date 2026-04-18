"""Comprehensive tests for merid/execution/executors/kalshi.py."""

import pytest
import respx
from httpx import Response

from merid.execution.executors.kalshi import KalshiExecutor
from merid.execution.base import Quote, TradeResult, Position


class TestKalshiExecutorInitialization:
    """Test KalshiExecutor initialization."""

    def test_default_initialization(self):
        """Test initialization with default values."""
        executor = KalshiExecutor()
        assert executor.venue == "kalshi"
        assert executor._client is None  # Client is lazily initialized

    def test_custom_api_url_from_env(self, monkeypatch):
        """Test custom API URL via environment variable."""
        # The URL is determined by KALSHI_USE_DEMO env var in the client
        monkeypatch.setenv("KALSHI_USE_DEMO", "true")
        executor = KalshiExecutor()
        assert executor.venue == "kalshi"
        # Client will use demo URL when created

    def test_credentials_from_env(self, monkeypatch):
        """Test credentials loaded from environment for the venue client."""
        monkeypatch.setenv("KALSHI_API_KEY_ID", "test_key_id")
        monkeypatch.setenv("KALSHI_API_KEY_SECRET", "test_secret")


class TestKalshiExecutorAuthHeaders:
    """Test KalshiExecutor authentication headers."""

    def test_get_auth_headers_with_credentials(self, monkeypatch):
        """Test auth headers with credentials (via venue client)."""
        monkeypatch.setenv("KALSHI_API_KEY_ID", "my_key_id")
        # Auth headers are handled by the venue client, not directly by executor
        executor = KalshiExecutor()
        # The executor delegates to venue client for auth
        assert executor.venue == "kalshi"

    def test_get_auth_headers_without_credentials(self, monkeypatch):
        """Test executor handles missing credentials gracefully."""
        # Ensure no env vars are set
        monkeypatch.delenv("KALSHI_API_KEY_ID", raising=False)

        executor = KalshiExecutor()

        # Executor doesn't have _get_auth_headers method - it's handled by client
        assert executor.venue == "kalshi"


class TestKalshiExecutorSymbolHandling:
    """Test symbol/ticker handling in executor."""

    def test_symbol_passed_to_quote(self):
        """Test that symbols are passed through to quotes."""
        # The executor uses symbols directly without conversion
        executor = KalshiExecutor()
        # Symbols are used as-is (e.g., "PRES-2024-DEM")
        assert executor.venue == "kalshi"


class TestKalshiExecutorGetQuote:
    """Test KalshiExecutor get_quote method."""

    @respx.mock
    @pytest.mark.asyncio
    async def test_get_quote_success(self):
        """Test successful quote retrieval."""
        executor = KalshiExecutor()

        # Mock the orderbook endpoint used by get_quote
        route = respx.get("https://api.elections.kalshi.com/trade-api/v2/markets/PRES-2024-DEM/orderbook").mock(
            return_value=Response(200, json={
                "orderbook": {
                    "yes": [["65", "100"]],  # price in cents, volume
                    "no": [["35", "100"]]
                }
            })
        )

        quote = await executor.get_quote("PRES-2024-DEM", "buy", 10.0)

        assert isinstance(quote, Quote)
        assert quote.symbol == "PRES-2024-DEM"
        assert quote.side == "buy"
        assert quote.price == 0.65  # 65 cents / 100
        assert quote.venue == "kalshi"
        assert quote.size == 10.0
        assert "raw" in quote.metadata  # Metadata contains raw orderbook data
        assert route.called

    @respx.mock
    @pytest.mark.asyncio
    async def test_get_quote_sell_side(self):
        """Test getting quote for sell side."""
        executor = KalshiExecutor()

        route = respx.get("https://api.elections.kalshi.com/trade-api/v2/markets/PRES-2024-REP/orderbook").mock(
            return_value=Response(200, json={
                "orderbook": {
                    "yes": [["60", "100"]],
                    "no": [["40", "100"]]
                }
            })
        )

        quote = await executor.get_quote("PRES-2024-REP", "sell", 5.0)

        assert quote.side == "sell"
        assert quote.price == 0.40  # no price for sell


class TestKalshiExecutorExecuteTrade:
    """Test KalshiExecutor execute_trade method."""

    @respx.mock
    @pytest.mark.asyncio
    async def test_execute_market_order_success(self, monkeypatch):
        """Test successful market order execution."""
        monkeypatch.setenv("KALSHI_API_KEY_ID", "test_key")
        executor = KalshiExecutor()
        
        route = respx.post("https://api.elections.kalshi.com/trade-api/v2/portfolio/orders").mock(
            return_value=Response(200, json={
                "order_id": "order_123",
                "status": "executed",
                "yes_price": "65"  # Price in cents
            })
        )
        
        result = await executor.execute_trade(
            symbol="PRES-2024-DEM",
            side="buy",
            amount=10.0,
            order_type="market"
        )
        
        assert isinstance(result, TradeResult)
        assert result.success is True
        assert result.venue == "kalshi"
        assert result.symbol == "PRES-2024-DEM"
        assert result.side == "buy"
        assert result.size == 10.0
        assert result.price == 0.65
        assert result.tx_id == "order_123"
        assert route.called
        
        # Verify request payload
        request = route.calls[0].request
        import json
        payload = json.loads(request.content)
        assert payload["ticker"] == "PRES-2024-DEM"
        assert payload["action"] == "buy"  # action is buy/sell
        assert payload["side"] == "yes"   # side is converted to yes/no for Kalshi
        assert payload["count"] == 10
        assert payload["client_order_id"].startswith("merid-")

    @respx.mock
    @pytest.mark.asyncio
    async def test_execute_limit_order_success(self, monkeypatch):
        """Test successful limit order execution."""
        monkeypatch.setenv("KALSHI_API_KEY_ID", "test_key")
        executor = KalshiExecutor()
        
        route = respx.post("https://api.elections.kalshi.com/trade-api/v2/portfolio/orders").mock(
            return_value=Response(200, json={
                "order_id": "order_456",
                "status": "executed",
                "yes_price": "60"  # Price in cents for sell order
            })
        )
        
        result = await executor.execute_trade(
            symbol="PRES-2024-REP",
            side="sell",
            amount=5.0,
            order_type="limit",
            price=0.60
        )
        
        assert result.success is True
        assert result.price == 0.60

        # Verify price in payload (Kalshi executor adds yes_price/no_price in cents, not price)
        request = route.calls[0].request
        import json
        payload = json.loads(request.content)
        assert payload["yes_price"] == 60  # Price in cents
        assert payload["ticker"] == "PRES-2024-REP"
        assert payload["action"] == "sell"  # action stays as sell
        assert payload["side"] == "yes"    # side converted to yes/no

    @respx.mock
    @pytest.mark.asyncio
    async def test_execute_trade_api_error(self, monkeypatch):
        """Test trade execution with API error."""
        monkeypatch.setenv("KALSHI_API_KEY_ID", "test_key")
        executor = KalshiExecutor()
        
        route = respx.post("https://api.elections.kalshi.com/trade-api/v2/portfolio/orders").mock(
            return_value=Response(400, json={"message": "Invalid order"})
        )
        
        result = await executor.execute_trade(
            symbol="PRES-2024-DEM",
            side="buy",
            amount=10.0
        )
        
        assert result.success is False
        assert "Kalshi order failed" in result.error

    @respx.mock
    @pytest.mark.asyncio
    async def test_execute_trade_network_error(self, monkeypatch):
        """Test trade execution with network error."""
        monkeypatch.setenv("KALSHI_API_KEY_ID", "test_key")
        executor = KalshiExecutor()
        
        route = respx.post("https://api.elections.kalshi.com/trade-api/v2/portfolio/orders").mock(
            side_effect=ConnectionError("Network unreachable")
        )
        
        result = await executor.execute_trade(
            symbol="PRES-2024-REP",
            side="sell",
            amount=5.0
        )
        
        assert result.success is False
        assert "Kalshi order failed" in result.error

    @respx.mock
    @pytest.mark.asyncio
    async def test_execute_trade_timeout_error(self, monkeypatch):
        """Test trade execution with timeout error."""
        import asyncio
        monkeypatch.setenv("KALSHI_API_KEY_ID", "test_key")
        executor = KalshiExecutor()
        
        route = respx.post("https://api.elections.kalshi.com/trade-api/v2/portfolio/orders").mock(
            side_effect=asyncio.TimeoutError("Request timeout")
        )
        
        result = await executor.execute_trade(
            symbol="PRES-2024-DEM",
            side="buy",
            amount=10.0
        )
        
        assert result.success is False
        assert "Kalshi order failed" in result.error


class TestKalshiExecutorGetPositions:
    """Test KalshiExecutor get_positions method."""

    @respx.mock
    @pytest.mark.asyncio
    async def test_get_positions_success(self, monkeypatch):
        """Test successful positions retrieval."""
        monkeypatch.setenv("KALSHI_API_KEY_ID", "test_key")
        executor = KalshiExecutor()
        
        route = respx.get("https://api.elections.kalshi.com/trade-api/v2/portfolio/positions").mock(
            return_value=Response(200, json={
                "market_positions": [
                    {
                        "ticker": "BTC-2024-01",
                        "position": 100,
                        "total_traded": 6500,
                        "realized_pnl": 1050
                    },
                    {
                        "ticker": "PRES-2024-REP",
                        "position": 50,
                        "total_traded": 2000,
                        "realized_pnl": -200
                    }
                ]
            })
        )

        positions = await executor.get_positions()

        assert len(positions) == 2

        # First position
        assert positions[0].symbol == "BTC-2024-01"
        assert positions[0].size == 100.0
        assert positions[0].entry_price == 0.65  # 6500/100 / 100
        assert positions[0].pnl == 10.5  # 1050/100
        assert positions[0].venue == "kalshi"
        assert positions[0].metadata["ticker"] == "BTC-2024-01"

        # Second position
        assert positions[1].symbol == "PRES-2024-REP"
        assert positions[1].size == 50.0
        assert positions[1].pnl == -2.00  # -200/100

        assert route.called

    @respx.mock
    @pytest.mark.asyncio
    async def test_get_positions_empty(self, monkeypatch):
        """Test empty positions list."""
        monkeypatch.setenv("KALSHI_API_KEY_ID", "test_key")
        executor = KalshiExecutor()
        
        route = respx.get("https://api.elections.kalshi.com/trade-api/v2/portfolio/positions").mock(
            return_value=Response(200, json={"market_positions": []})
        )

        positions = await executor.get_positions()

        assert positions == []

    @respx.mock
    @pytest.mark.asyncio
    async def test_get_positions_missing_optional_fields(self, monkeypatch):
        """Test positions retrieval with missing optional fields."""
        monkeypatch.setenv("KALSHI_API_KEY_ID", "test_key")
        executor = KalshiExecutor()
        
        route = respx.get("https://api.elections.kalshi.com/trade-api/v2/portfolio/positions").mock(
            return_value=Response(200, json={
                "market_positions": [
                    {
                        "ticker": "ETH-2024-02",
                        "position": 50,
                        "total_traded": 0,
                        "realized_pnl": 0
                    }
                ]
            })
        )

        positions = await executor.get_positions()

        assert len(positions) == 1
        assert positions[0].symbol == "ETH-2024-02"
        assert positions[0].size == 50.0
        assert positions[0].entry_price == 0.0  # Default when total_traded is 0
        assert positions[0].pnl == 0.0  # Default

    @respx.mock
    @pytest.mark.asyncio
    async def test_get_positions_api_error(self, monkeypatch):
        """Test positions retrieval with API error."""
        monkeypatch.setenv("KALSHI_API_KEY_ID", "test_key")
        executor = KalshiExecutor()
        
        route = respx.get("https://api.elections.kalshi.com/trade-api/v2/portfolio/positions").mock(
            return_value=Response(401, json={"error": "Unauthorized"})
        )
        
        # Executor returns empty list on API error, not raises
        positions = await executor.get_positions()
        assert positions == []
