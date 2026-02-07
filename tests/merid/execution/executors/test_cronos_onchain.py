"""Comprehensive tests for merid/execution/executors/cronos_onchain.py."""

import pytest
import respx
from httpx import Response

from merid.execution.executors.cronos_onchain import CronosOnchainExecutor
from merid.execution.base import Quote, TradeResult, Position


class TestCronosOnchainExecutorInitialization:
    """Test CronosOnchainExecutor initialization."""

    def test_default_initialization(self):
        """Test initialization with default values."""
        executor = CronosOnchainExecutor()
        assert executor.venue == "cronos_onchain"
        assert executor.base_url == "https://evm-cronos.crypto.org"
        assert executor.default_timeout == 10.0

    def test_custom_rpc_url_from_env(self, monkeypatch):
        """Test custom RPC URL from environment variable."""
        # base_url is a class attribute evaluated at definition time,
        # so we patch the class attribute directly
        monkeypatch.setattr(CronosOnchainExecutor, "base_url", "https://test.cronos.org")
        executor = CronosOnchainExecutor()
        assert executor.base_url == "https://test.cronos.org"

    def test_private_key_from_env(self, monkeypatch):
        """Test private key loaded from environment."""
        monkeypatch.setenv("CRONOS_PRIVATE_KEY", "0xprivatekey123")
        
        executor = CronosOnchainExecutor()
        assert executor.private_key == "0xprivatekey123"


class TestCronosOnchainExecutorAuthHeaders:
    """Test CronosOnchainExecutor authentication headers."""

    def test_get_auth_headers(self):
        """Test auth headers include Content-Type."""
        executor = CronosOnchainExecutor()
        
        headers = executor._get_auth_headers()
        
        assert headers["Content-Type"] == "application/json"


class TestCronosOnchainExecutorFetchPrice:
    """Test _fetch_price method."""

    @pytest.mark.asyncio
    async def test_fetch_known_prices(self):
        """Test fetching known token prices."""
        executor = CronosOnchainExecutor()
        
        eth_price = await executor._fetch_price("ETH", "USDC")
        assert eth_price == 3000.0
        
        btc_price = await executor._fetch_price("BTC", "USDC")
        assert btc_price == 50000.0
        
        cro_price = await executor._fetch_price("CRO", "USDC")
        assert cro_price == 0.08

    @pytest.mark.asyncio
    async def test_fetch_unknown_price_defaults_to_one(self):
        """Test fetching unknown token price defaults to 1.0."""
        executor = CronosOnchainExecutor()
        
        price = await executor._fetch_price("UNKNOWN", "TOKEN")
        
        assert price == 1.0


class TestCronosOnchainExecutorTokenBalance:
    """Test _token_balance method."""

    @pytest.mark.asyncio
    async def test_fetch_known_balances(self):
        """Test fetching known token balances."""
        executor = CronosOnchainExecutor()
        
        usdc_balance = await executor._token_balance("USDC")
        assert usdc_balance == 1234.56
        
        eth_balance = await executor._token_balance("ETH")
        assert eth_balance == 0.5
        
        cro_balance = await executor._token_balance("CRO")
        assert cro_balance == 1000.0

    @pytest.mark.asyncio
    async def test_fetch_unknown_balance_defaults_to_zero(self):
        """Test fetching unknown token balance defaults to 0.0."""
        executor = CronosOnchainExecutor()
        
        balance = await executor._token_balance("UNKNOWN")
        
        assert balance == 0.0


class TestCronosOnchainExecutorGetQuote:
    """Test CronosOnchainExecutor get_quote method."""

    @pytest.mark.asyncio
    async def test_get_quote_buy_success(self):
        """Test successful buy quote retrieval."""
        executor = CronosOnchainExecutor()
        
        quote = await executor.get_quote("ETH-USDC", "buy", 2.0)
        
        assert isinstance(quote, Quote)
        assert quote.symbol == "ETH-USDC"
        assert quote.side == "buy"
        assert quote.price == 3000.0
        assert quote.venue == "cronos_onchain"
        assert quote.size == 2.0
        assert quote.metadata["base"] == "ETH"
        assert quote.metadata["quote"] == "USDC"

    @pytest.mark.asyncio
    async def test_get_quote_sell_success(self):
        """Test successful sell quote retrieval."""
        executor = CronosOnchainExecutor()
        
        quote = await executor.get_quote("BTC-USDC", "sell", 0.5)
        
        assert quote.side == "sell"
        assert quote.price == 50000.0

    @pytest.mark.asyncio
    async def test_get_quote_unknown_pair(self):
        """Test quote for unknown pair uses default price."""
        executor = CronosOnchainExecutor()
        
        quote = await executor.get_quote("UNKNOWN-PAIR", "buy", 100.0)
        
        assert quote.price == 1.0


class TestCronosOnchainExecutorExecuteTrade:
    """Test CronosOnchainExecutor execute_trade method."""

    @pytest.mark.asyncio
    async def test_execute_market_order_success(self):
        """Test successful market order execution."""
        executor = CronosOnchainExecutor()
        
        result = await executor.execute_trade(
            symbol="ETH-USDC",
            side="buy",
            amount=2.0,
            order_type="market"
        )
        
        assert isinstance(result, TradeResult)
        assert result.success is True
        assert result.venue == "cronos_onchain"
        assert result.symbol == "ETH-USDC"
        assert result.side == "buy"
        assert result.size == 2.0
        assert result.price == 3000.0
        assert result.tx_id.startswith("0x")
        assert len(result.tx_id) > 0  # tx_id is present

    @pytest.mark.asyncio
    async def test_execute_limit_order_success(self):
        """Test successful limit order execution with specified price."""
        executor = CronosOnchainExecutor()
        
        result = await executor.execute_trade(
            symbol="BTC-USDC",
            side="sell",
            amount=0.5,
            order_type="limit",
            price=55000.0
        )
        
        assert result.success is True
        assert result.price == 55000.0  # Uses provided price

    @pytest.mark.asyncio
    async def test_execute_trade_metadata(self):
        """Test execution result metadata."""
        executor = CronosOnchainExecutor()
        
        result = await executor.execute_trade(
            symbol="CRO-USDC",
            side="buy",
            amount=1000.0
        )
        
        assert result.metadata["base"] == "CRO"
        assert result.metadata["quote"] == "USDC"


class TestCronosOnchainExecutorGetPositions:
    """Test CronosOnchainExecutor get_positions method."""

    @pytest.mark.asyncio
    async def test_get_positions_with_usdc_balance(self):
        """Test positions when USDC balance exists."""
        executor = CronosOnchainExecutor()
        
        positions = await executor.get_positions()
        
        assert len(positions) == 1
        assert positions[0].symbol == "USDC-CRO"
        assert positions[0].size == 1234.56
        assert positions[0].venue == "cronos_onchain"
        assert positions[0].metadata["token"] == "USDC"

    @pytest.mark.asyncio
    async def test_get_positions_usdc_only(self):
        """Test that only USDC position is returned."""
        executor = CronosOnchainExecutor()
        
        positions = await executor.get_positions()
        
        # Only USDC is checked in get_positions
        assert len(positions) == 1
        assert all(p.symbol == "USDC-CRO" for p in positions)
