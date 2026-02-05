"""Comprehensive tests for Alpaca executor - HTTP mocking with respx."""

import pytest
import respx
from httpx import Response
from decimal import Decimal

from merid.execution.executors.alpaca import AlpacaExecutor
from merid.execution.base import Quote, TradeResult, Position


@pytest.fixture
def executor():
    """Create test Alpaca executor."""
    return AlpacaExecutor()


class TestAlpacaExecutorInitialization:
    """Test AlpacaExecutor initialization."""
    
    def test_initialization(self, executor):
        """Test executor initialization."""
        assert executor.venue == "alpaca"
        assert executor.base_url == "https://paper-api.alpaca.markets"
        assert executor.default_timeout == 10.0
    
    def test_auth_headers(self, executor):
        """Test auth headers generation."""
        headers = executor._get_auth_headers()
        
        assert "APCA-API-KEY-ID" in headers
        assert "APCA-API-SECRET-KEY" in headers


@respx.mock
class TestAlpacaExecutorQuotes:
    """Test AlpacaExecutor quote functionality."""
    
    async def test_get_quote_buy(self, executor):
        """Test get_quote for buy side."""
        route = respx.get("https://paper-api.alpaca.markets/v2/stocks/AAPL/quotes/latest").mock(
            return_value=Response(200, json={
                "quote": {
                    "ap": "150.50",  # ask price
                    "bp": "150.00"   # bid price
                }
            })
        )
        
        quote = await executor.get_quote("AAPL", "buy", 100.0)
        
        assert isinstance(quote, Quote)
        assert quote.symbol == "AAPL"
        assert quote.side == "buy"
        assert quote.price == 150.50  # Uses ask price for buy
        assert quote.venue == "alpaca"
        assert quote.size == 100.0
        assert route.called
    
    async def test_get_quote_sell(self, executor):
        """Test get_quote for sell side."""
        respx.get("https://paper-api.alpaca.markets/v2/stocks/TSLA/quotes/latest").mock(
            return_value=Response(200, json={
                "quote": {
                    "ap": "200.00",
                    "bp": "199.50"
                }
            })
        )
        
        quote = await executor.get_quote("TSLA", "sell", 50.0)
        
        assert quote.symbol == "TSLA"
        assert quote.side == "sell"
        assert quote.price == 199.50  # Uses bid price for sell
        assert quote.size == 50.0


@respx.mock
class TestAlpacaExecutorTrading:
    """Test AlpacaExecutor trading functionality."""
    
    async def test_execute_trade_market(self, executor):
        """Test execute_trade with market order."""
        route = respx.post("https://paper-api.alpaca.markets/v2/orders").mock(
            return_value=Response(200, json={
                "id": "order_123",
                "filled_avg_price": "150.25",
                "status": "filled"
            })
        )
        
        result = await executor.execute_trade("AAPL", "buy", 100.0)
        
        assert isinstance(result, TradeResult)
        assert result.success is True
        assert result.venue == "alpaca"
        assert result.symbol == "AAPL"
        assert result.side == "buy"
        assert result.size == 100.0
        assert result.price == 150.25
        assert result.tx_id == "order_123"
        assert route.called
    
    async def test_execute_trade_limit(self, executor):
        """Test execute_trade with limit order."""
        respx.post("https://paper-api.alpaca.markets/v2/orders").mock(
            return_value=Response(200, json={
                "id": "order_456",
                "filled_avg_price": "200.00",
                "status": "filled"
            })
        )
        
        result = await executor.execute_trade(
            "TSLA", "sell", 50.0,
            order_type="limit",
            price=200.0
        )
        
        assert result.success is True
        assert result.price == 200.0
    
    async def test_execute_trade_error(self, executor):
        """Test execute_trade with API error."""
        respx.post("https://paper-api.alpaca.markets/v2/orders").mock(
            return_value=Response(400, text="Insufficient funds")
        )
        
        result = await executor.execute_trade("AAPL", "buy", 1000.0)
        
        assert isinstance(result, TradeResult)
        assert result.success is False
        assert "error" in result.error.lower() or "alpaca" in result.error.lower()


@respx.mock
class TestAlpacaExecutorPositions:
    """Test AlpacaExecutor positions functionality."""
    
    async def test_get_positions(self, executor):
        """Test get_positions."""
        route = respx.get("https://paper-api.alpaca.markets/v2/positions").mock(
            return_value=Response(200, json=[
                {
                    "symbol": "AAPL",
                    "qty": "100",
                    "avg_entry_price": "145.00",
                    "unrealized_plpc": "5000",  # In basis points
                    "asset_id": "asset_123"
                },
                {
                    "symbol": "TSLA",
                    "qty": "50",
                    "avg_entry_price": "200.00",
                    "unrealized_plpc": "-2000",
                    "asset_id": "asset_456"
                }
            ])
        )
        
        positions = await executor.get_positions()
        
        assert len(positions) == 2
        assert isinstance(positions[0], Position)
        assert positions[0].symbol == "AAPL"
        assert positions[0].size == 100.0
        assert positions[0].entry_price == 145.0
        # PnL is divided by 10000 (basis points to decimal)
        assert positions[0].pnl == 0.5
        assert route.called
    
    async def test_get_positions_empty(self, executor):
        """Test get_positions with empty response."""
        respx.get("https://paper-api.alpaca.markets/v2/positions").mock(
            return_value=Response(200, json=[])
        )
        
        positions = await executor.get_positions()
        
        assert len(positions) == 0
