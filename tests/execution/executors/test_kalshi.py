"""Comprehensive tests for Kalshi executor - HTTP mocking with respx."""

import pytest
import respx
from httpx import Response
from unittest.mock import MagicMock

from merid.execution.executors.kalshi import KalshiExecutor
from merid.execution.base import Quote, TradeResult, Position


@pytest.fixture
def executor():
    """Create test Kalshi executor."""
    return KalshiExecutor()


class TestKalshiExecutorInitialization:
    """Test KalshExecutor initialization."""
    
    def test_initialization(self, executor):
        """Test executor initialization."""
        assert executor.venue == "kalshi"
        # Note: base_url and default_timeout are delegated to KalshiVenueClient
        # These are not direct attributes of KalshiExecutor in current implementation


@respx.mock
class TestKalshiExecutorQuotes:
    """Test KalshiExecutor quote functionality."""
    
    async def test_get_quote_success(self, executor):
        """Test get_quote success."""
        route = respx.get(
            "https://api.elections.kalshi.com/trade/v1/price",
            params={"ticker": "PRES-2024-DEM", "side": "buy", "count": "100"}
        ).mock(
            return_value=Response(200, json={"price": "65.5"})
        )
        
        quote = await executor.get_quote("PRES-2024-DEM", "buy", 100.0)
        
        assert isinstance(quote, Quote)
        assert quote.symbol == "PRES-2024-DEM"
        assert quote.side == "buy"
        assert quote.price == 65.5
        assert quote.venue == "kalshi"
        assert quote.size == 100.0
        assert route.called
    
    async def test_get_quote_converts_symbol(self, executor):
        """Test get_quote converts symbol to ticker."""
        respx.get(
            "https://api.elections.kalshi.com/trade/v1/price",
            params={"ticker": "PRES-2024-REP", "side": "sell", "count": "50"}
        ).mock(
            return_value=Response(200, json={"price": "35.0"})
        )
        
        quote = await executor.get_quote("PRES-2024-REP", "sell", 50.0)
        
        assert quote.symbol == "PRES-2024-REP"
        assert quote.price == 35.0


@respx.mock
class TestKalshiExecutorTrading:
    """Test KalshiExecutor trading functionality."""
    
    async def test_execute_trade_market(self, executor):
        """Test execute_trade with market order."""
        route = respx.post("https://api.elections.kalshi.com/trade/v1/order").mock(
            return_value=Response(200, json={
                "order_id": "order_123",
                "executed_price": "65.5"
            })
        )
        
        result = await executor.execute_trade("PRES-2024-DEM", "buy", 100.0)
        
        assert isinstance(result, TradeResult)
        assert result.success is True
        assert result.venue == "kalshi"
        assert result.symbol == "PRES-2024-DEM"
        assert result.side == "buy"
        assert result.size == 100.0
        assert result.price == 65.5
        assert result.tx_id == "order_123"
        assert route.called
    
    async def test_execute_trade_limit(self, executor):
        """Test execute_trade with limit order."""
        respx.post("https://api.elections.kalshi.com/trade/v1/order").mock(
            return_value=Response(200, json={
                "order_id": "order_456",
                "executed_price": "60.0"
            })
        )
        
        result = await executor.execute_trade(
            "PRES-2024-DEM", "buy", 100.0,
            order_type="limit",
            price=60.0
        )
        
        assert result.success is True
        assert result.price == 60.0
    
    async def test_execute_trade_error(self, executor):
        """Test execute_trade with API error."""
        respx.post("https://api.elections.kalshi.com/trade/v1/order").mock(
            return_value=Response(400, text="Insufficient funds")
        )
        
        result = await executor.execute_trade("PRES-2024-DEM", "buy", 1000.0)
        
        assert isinstance(result, TradeResult)
        assert result.success is False
        assert "kalshi" in result.error.lower()


@respx.mock
class TestKalshiExecutorPositions:
    """Test KalshiExecutor positions functionality."""
    
    async def test_get_positions(self, executor):
        """Test get_positions."""
        route = respx.get("https://api.elections.kalshi.com/portfolio/v1/positions").mock(
            return_value=Response(200, json={
                "positions": [
                    {
                        "ticker": "PRES-2024-DEM",
                        "count": "100",
                        "avg_price": "60.0",
                        "pnl": "500.0"
                    },
                    {
                        "ticker": "PRES-2024-REP",
                        "count": "50",
                        "avg_price": "40.0",
                        "pnl": "-200.0"
                    }
                ]
            })
        )
        
        positions = await executor.get_positions()
        
        assert len(positions) == 2
        assert isinstance(positions[0], Position)
        assert positions[0].symbol == "PRES-2024-DEM"
        assert positions[0].size == 100.0
        assert positions[0].entry_price == 60.0
        assert positions[0].pnl == 500.0
        assert positions[1].symbol == "PRES-2024-REP"
        assert positions[1].size == 50.0
        assert route.called
    
    async def test_get_positions_empty(self, executor):
        """Test get_positions with empty response."""
        respx.get("https://api.elections.kalshi.com/portfolio/v1/positions").mock(
            return_value=Response(200, json={"positions": []})
        )
        
        positions = await executor.get_positions()
        
        assert len(positions) == 0


@pytest.mark.skip(
    reason=(
        "KalshiExecutor._symbol_to_ticker / _ticker_to_symbol helpers were "
        "removed when the executor began delegating symbol/ticker coercion "
        "to KalshiVenueClient + the order router. See "
        "merid/event_venues/kalshi/client.py for the canonical mapping and "
        "tests/event_venues/kalshi/test_kalshi_client_refactored.py for the "
        "covering suite."
    )
)
class TestKalshiExecutorHelpers:
    """Test KalshiExecutor helper methods."""
    
    def test_symbol_to_ticker_mapping(self, executor):
        """Test symbol to ticker conversion with mapping."""
        ticker = executor._symbol_to_ticker("PRES-2024-DEM")
        assert ticker == "PRES-2024-DEM"
    
    def test_symbol_to_ticker_default(self, executor):
        """Test symbol to ticker conversion without mapping."""
        ticker = executor._symbol_to_ticker("FED-25DEC")
        assert ticker == "FED-25DEC"
    
    def test_ticker_to_symbol_mapping(self, executor):
        """Test ticker to symbol conversion with mapping."""
        symbol = executor._ticker_to_symbol("PRES-2024-REP")
        assert symbol == "PRES-2024-REP"
    
    def test_ticker_to_symbol_default(self, executor):
        """Test ticker to symbol conversion without mapping."""
        symbol = executor._ticker_to_symbol("BTC-24DEC")
        assert symbol == "BTC-24DEC"
