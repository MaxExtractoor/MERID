"""Comprehensive tests for merid/execution/executors/cronos_onchain.py - Coverage improvement."""

import pytest
from unittest.mock import MagicMock, patch, AsyncMock

from merid.execution.executors.cronos_onchain import CronosOnchainExecutor


@pytest.fixture
def executor(monkeypatch):
    """Create CronosOnchainExecutor with mocked environment."""
    monkeypatch.setenv("CRONOS_PRIVATE_KEY", "test_private_key")
    
    executor = CronosOnchainExecutor()
    return executor


# =============================================================================
# Initialization Tests
# =============================================================================

class TestCronosOnchainExecutorInit:
    """Test CronosOnchainExecutor initialization."""

    def test_init_with_key(self, monkeypatch):
        monkeypatch.setenv("CRONOS_PRIVATE_KEY", "priv_key")
        
        executor = CronosOnchainExecutor()
        
        assert executor.venue == "cronos_onchain"
        assert executor.private_key == "priv_key"

    def test_init_defaults(self, monkeypatch):
        monkeypatch.delenv("CRONOS_PRIVATE_KEY", raising=False)
        
        executor = CronosOnchainExecutor()
        
        assert executor.private_key is None


class TestGetAuthHeaders:
    """Test _get_auth_headers method."""

    def test_auth_headers(self, executor):
        headers = executor._get_auth_headers()
        assert headers["Content-Type"] == "application/json"


# =============================================================================
# Get Quote Tests
# =============================================================================

class TestGetQuote:
    """Test get_quote method."""

    @pytest.mark.asyncio
    async def test_get_quote_eth_usdc(self, executor):
        quote = await executor.get_quote("ETH-USDC", "buy", 1.0)
        
        assert quote.symbol == "ETH-USDC"
        assert quote.side == "buy"
        assert quote.price == 3000.0
        assert quote.venue == "cronos_onchain"

    @pytest.mark.asyncio
    async def test_get_quote_btc_usdc(self, executor):
        quote = await executor.get_quote("BTC-USDC", "sell", 0.1)
        
        assert quote.price == 50000.0

    @pytest.mark.asyncio
    async def test_get_quote_cro_usdc(self, executor):
        quote = await executor.get_quote("CRO-USDC", "buy", 1000.0)
        
        assert quote.price == 0.08

    @pytest.mark.asyncio
    async def test_get_quote_unknown_pair(self, executor):
        quote = await executor.get_quote("UNKNOWN-TOKEN", "buy", 100.0)
        
        assert quote.price == 1.0  # Default price


# =============================================================================
# Execute Trade Tests
# =============================================================================

class TestExecuteTrade:
    """Test execute_trade method."""

    @pytest.mark.asyncio
    async def test_execute_trade_success(self, executor):
        result = await executor.execute_trade(
            symbol="ETH-USDC",
            side="buy",
            amount=1.0
        )
        
        assert result.success is True
        assert result.venue == "cronos_onchain"
        assert result.tx_id is not None
        assert result.price == 3000.0

    @pytest.mark.asyncio
    async def test_execute_trade_with_price(self, executor):
        result = await executor.execute_trade(
            symbol="BTC-USDC",
            side="sell",
            amount=0.5,
            price=48000.0
        )
        
        assert result.success is True
        assert result.price == 48000.0

    @pytest.mark.asyncio
    async def test_execute_trade_metadata(self, executor):
        result = await executor.execute_trade(
            symbol="CRO-USDC",
            side="buy",
            amount=1000.0
        )
        
        assert result.metadata["base"] == "CRO"
        assert result.metadata["quote"] == "USDC"


# =============================================================================
# Get Positions Tests
# =============================================================================

class TestGetPositions:
    """Test get_positions method."""

    @pytest.mark.asyncio
    async def test_get_positions_with_usdc(self, executor):
        positions = await executor.get_positions()
        
        assert len(positions) == 1
        assert positions[0].symbol == "USDC-CRO"
        assert positions[0].size == 1234.56


# =============================================================================
# Fetch Price Tests
# =============================================================================

class TestFetchPrice:
    """Test _fetch_price method."""

    @pytest.mark.asyncio
    async def test_fetch_price_eth_usdc(self, executor):
        price = await executor._fetch_price("ETH", "USDC")
        assert price == 3000.0

    @pytest.mark.asyncio
    async def test_fetch_price_btc_usdc(self, executor):
        price = await executor._fetch_price("BTC", "USDC")
        assert price == 50000.0

    @pytest.mark.asyncio
    async def test_fetch_price_unknown(self, executor):
        price = await executor._fetch_price("UNKNOWN", "TOKEN")
        assert price == 1.0


# =============================================================================
# Token Balance Tests
# =============================================================================

class TestTokenBalance:
    """Test _token_balance method."""

    @pytest.mark.asyncio
    async def test_token_balance_usdc(self, executor):
        balance = await executor._token_balance("USDC")
        assert balance == 1234.56

    @pytest.mark.asyncio
    async def test_token_balance_eth(self, executor):
        balance = await executor._token_balance("ETH")
        assert balance == 0.5

    @pytest.mark.asyncio
    async def test_token_balance_cro(self, executor):
        balance = await executor._token_balance("CRO")
        assert balance == 1000.0

    @pytest.mark.asyncio
    async def test_token_balance_unknown(self, executor):
        balance = await executor._token_balance("UNKNOWN")
        assert balance == 0.0


# =============================================================================
# Class Attributes Tests
# =============================================================================

class TestClassAttributes:
    """Test class-level attributes."""

    def test_venue_name(self):
        assert CronosOnchainExecutor.venue == "cronos_onchain"

    def test_default_timeout(self):
        assert CronosOnchainExecutor.default_timeout == 10.0
