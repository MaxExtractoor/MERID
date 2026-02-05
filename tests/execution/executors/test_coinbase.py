"""Comprehensive tests for Coinbase executor - HTTP mocking with respx."""

import pytest
import respx
import hmac
import hashlib
import time
from httpx import Response
from unittest.mock import MagicMock, patch

from merid.execution.executors.coinbase import CoinbaseExecutor
from merid.execution.base import Quote, TradeResult, Position


@pytest.fixture
def executor():
    """Create test Coinbase executor."""
    return CoinbaseExecutor()


class TestCoinbaseExecutorInitialization:
    """Test CoinbaseExecutor initialization."""
    
    def test_initialization(self, executor):
        """Test executor initialization."""
        assert executor.venue == "coinbase"
        assert executor.base_url == "https://api.coinbase.com"
        assert executor.default_timeout == 10.0
    
    def test_auth_headers_empty(self, executor):
        """Test auth headers returns empty dict."""
        headers = executor._get_auth_headers()
        assert headers == {}


class TestCoinbaseExecutorSigning:
    """Test CoinbaseExecutor signature generation."""
    
    def test_sign_generation(self, executor):
        """Test signature generation."""
        executor.api_key = "test_key"
        executor.api_secret = "test_secret"
        executor.passphrase = "test_passphrase"
        
        headers = executor._sign("GET", "/v2/accounts", "")
        
        assert "CB-ACCESS-KEY" in headers
        assert headers["CB-ACCESS-KEY"] == "test_key"
        assert "CB-ACCESS-SIGN" in headers
        assert len(headers["CB-ACCESS-SIGN"]) == 64  # SHA256 hex length
        assert "CB-ACCESS-TIMESTAMP" in headers
        assert "CB-ACCESS-PASSPHRASE" in headers
        assert headers["CB-ACCESS-PASSPHRASE"] == "test_passphrase"
    
    def test_sign_with_body(self, executor):
        """Test signature generation with body."""
        executor.api_secret = "test_secret"
        
        headers = executor._sign("POST", "/v2/orders", '{"test": "data"}')
        
        assert "CB-ACCESS-SIGN" in headers
        # Signature should be different with body
        assert len(headers["CB-ACCESS-SIGN"]) == 64


@respx.mock
class TestCoinbaseExecutorQuotes:
    """Test CoinbaseExecutor quote functionality."""
    
    async def test_get_quote_success(self, executor):
        """Test get_quote success."""
        route = respx.get("https://api.coinbase.com/v2/products/BTC-USD/ticker").mock(
            return_value=Response(200, json={"price": "50000.00"})
        )
        
        quote = await executor.get_quote("BTC-USD", "buy", 0.5)
        
        assert isinstance(quote, Quote)
        assert quote.symbol == "BTC-USD"
        assert quote.side == "buy"
        assert quote.price == 50000.00
        assert quote.venue == "coinbase"
        assert quote.size == 0.5
        assert route.called
    
    async def test_get_quote_converts_symbol(self, executor):
        """Test get_quote converts symbol to product ID."""
        route = respx.get("https://api.coinbase.com/v2/products/ETH-USD/ticker").mock(
            return_value=Response(200, json={"price": "3000.00"})
        )
        
        quote = await executor.get_quote("ETH-USDT", "sell", 1.0)
        
        # Should convert ETH-USDT to ETH-USD
        assert quote.symbol == "ETH-USDT"
        assert quote.price == 3000.00


@respx.mock
class TestCoinbaseExecutorTrading:
    """Test CoinbaseExecutor trading functionality."""
    
    async def test_execute_trade_market(self, executor):
        """Test execute_trade with market order."""
        route = respx.post("https://api.coinbase.com/v2/orders").mock(
            return_value=Response(200, json={
                "id": "order_123",
                "executed_value": "25000.00"
            })
        )
        
        result = await executor.execute_trade("BTC-USD", "buy", 0.5)
        
        assert isinstance(result, TradeResult)
        assert result.success is True
        assert result.venue == "coinbase"
        assert result.symbol == "BTC-USD"
        assert result.side == "buy"
        assert result.size == 0.5
        assert result.price == 50000.00  # 25000 / 0.5
        assert result.tx_id == "order_123"
        assert route.called
    
    async def test_execute_trade_limit(self, executor):
        """Test execute_trade with limit order."""
        respx.post("https://api.coinbase.com/v2/orders").mock(
            return_value=Response(200, json={
                "id": "order_456",
                "executed_value": "15000.00"
            })
        )
        
        result = await executor.execute_trade(
            "ETH-USD", "sell", 5.0,
            order_type="limit",
            price=3000.0
        )
        
        assert result.success is True
        assert result.price == 3000.0  # 15000 / 5
    
    async def test_execute_trade_error(self, executor):
        """Test execute_trade with API error."""
        respx.post("https://api.coinbase.com/v2/orders").mock(
            return_value=Response(400, text="Insufficient funds")
        )
        
        result = await executor.execute_trade("BTC-USD", "buy", 10.0)
        
        assert isinstance(result, TradeResult)
        assert result.success is False
        assert "error" in result.error.lower()


@respx.mock
class TestCoinbaseExecutorPositions:
    """Test CoinbaseExecutor positions functionality."""
    
    async def test_get_positions(self, executor):
        """Test get_positions."""
        route = respx.get("https://api.coinbase.com/v2/accounts").mock(
            return_value=Response(200, json={
                "data": [
                    {
                        "id": "acct_1",
                        "type": "wallet",
                        "currency": "BTC",
                        "available": {"value": "0.5"}
                    },
                    {
                        "id": "acct_2",
                        "type": "wallet",
                        "currency": "ETH",
                        "available": {"value": "2.0"}
                    },
                    {
                        "id": "acct_3",
                        "type": "fiat",  # Should be skipped
                        "currency": "USD",
                        "available": {"value": "1000.0"}
                    }
                ]
            })
        )
        
        positions = await executor.get_positions()
        
        assert len(positions) == 2
        assert isinstance(positions[0], Position)
        assert positions[0].symbol == "BTC-USD"
        assert positions[0].size == 0.5
        assert positions[1].symbol == "ETH-USD"
        assert positions[1].size == 2.0
        assert route.called
    
    async def test_get_positions_empty(self, executor):
        """Test get_positions with empty response."""
        respx.get("https://api.coinbase.com/v2/accounts").mock(
            return_value=Response(200, json={"data": []})
        )
        
        positions = await executor.get_positions()
        
        assert len(positions) == 0
    
    async def test_get_positions_zero_balance(self, executor):
        """Test get_positions filters zero balance accounts."""
        respx.get("https://api.coinbase.com/v2/accounts").mock(
            return_value=Response(200, json={
                "data": [
                    {
                        "id": "acct_1",
                        "type": "wallet",
                        "currency": "BTC",
                        "available": {"value": "0.0"}  # Zero balance
                    }
                ]
            })
        )
        
        positions = await executor.get_positions()
        
        assert len(positions) == 0


class TestCoinbaseExecutorHelpers:
    """Test CoinbaseExecutor helper methods."""
    
    def test_to_product_id_usd(self, executor):
        """Test symbol to product ID conversion with USD."""
        product_id = executor._to_product_id("BTC-USD")
        assert product_id == "BTC-USD"
    
    def test_to_product_id_usdt(self, executor):
        """Test symbol to product ID conversion with USDT."""
        product_id = executor._to_product_id("ETH-USDT")
        assert product_id == "ETH-USD"
    
    def test_to_product_id_other(self, executor):
        """Test symbol to product ID conversion with other quote."""
        product_id = executor._to_product_id("BTC-EUR")
        assert product_id == "BTC-EUR"
