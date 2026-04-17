"""Comprehensive tests for trading/adapters/pumpfun.py - Coverage improvement."""

import pytest
from unittest.mock import MagicMock, patch
import httpx

from trading.adapters.base import TradeRequest, TradeSide
from trading.adapters.pumpfun import PumpFunAdapter


@pytest.fixture
def adapter(monkeypatch):
    """Create PumpFunAdapter with mocked HTTP client."""
    monkeypatch.delenv("PUMPFUN_WALLET_SECRET", raising=False)
    
    with patch.object(httpx, 'Client') as mock_client:
        adapter = PumpFunAdapter()
        adapter._http = MagicMock()
        return adapter


@pytest.fixture
def adapter_with_wallet(monkeypatch):
    """Create PumpFunAdapter with wallet secret configured."""
    monkeypatch.setenv("PUMPFUN_WALLET_SECRET", "test_wallet_secret")
    
    with patch.object(httpx, 'Client') as mock_client:
        adapter = PumpFunAdapter()
        adapter._http = MagicMock()
        return adapter


# =============================================================================
# Initialization Tests
# =============================================================================

class TestPumpFunAdapterInit:
    """Test PumpFunAdapter initialization."""

    def test_init_defaults(self, monkeypatch):
        monkeypatch.delenv("PUMPFUN_API_BASE", raising=False)
        monkeypatch.delenv("PUMPFUN_WALLET_SECRET", raising=False)
        
        with patch.object(httpx, 'Client'):
            adapter = PumpFunAdapter()
        
        assert adapter.venue == "pumpfun"
        assert adapter.supports_trading is True
        assert adapter.api_base == "https://pump.fun/api"
        assert adapter.wallet_secret is None

    def test_init_custom_api_base(self, monkeypatch):
        monkeypatch.delenv("PUMPFUN_API_BASE", raising=False)
        
        with patch.object(httpx, 'Client'):
            adapter = PumpFunAdapter(api_base="https://custom.pump.fun/api")
        
        assert adapter.api_base == "https://custom.pump.fun/api"

    def test_init_from_env(self, monkeypatch):
        monkeypatch.setenv("PUMPFUN_API_BASE", "https://env.pump.fun/api")
        monkeypatch.setenv("PUMPFUN_WALLET_SECRET", "secret_key")
        
        with patch.object(httpx, 'Client'):
            adapter = PumpFunAdapter()
        
        assert adapter.api_base == "https://env.pump.fun/api"
        assert adapter.wallet_secret == "secret_key"


# =============================================================================
# Submit Order Tests
# =============================================================================

class TestSubmitOrderLive:
    """Test _submit_order_live method."""

    def test_submit_order_no_token_address_raises(self, adapter):
        """Test order without token_address raises error."""
        request = TradeRequest(
            venue="pumpfun",
            symbol="MEMECOIN",
            side=TradeSide.BUY,
            quantity=1.0,
            metadata={}
        )
        
        with pytest.raises(RuntimeError, match="token_address"):
            adapter._submit_order_live(request)

    def test_submit_order_with_token_address(self, adapter):
        """Test successful order with token_address."""
        adapter._http.get.return_value = MagicMock(
            json=lambda: {"trades": [{"priceSol": 0.001}]},
            raise_for_status=lambda: None
        )
        
        request = TradeRequest(
            venue="pumpfun",
            symbol="MEME",
            side=TradeSide.BUY,
            quantity=10.0,
            metadata={"token_address": "So11111111111111111111111111111111111111112"}
        )
        
        result = adapter._submit_order_live(request)
        
        assert result.venue == "pumpfun"
        assert result.status == "simulated"
        assert result.executed_price == 0.001

    def test_submit_order_with_mint_key(self, adapter):
        """Test order with 'mint' key instead of 'token_address'."""
        adapter._http.get.return_value = MagicMock(
            json=lambda: {"trades": [{"price": 0.002}]},
            raise_for_status=lambda: None
        )
        
        request = TradeRequest(
            venue="pumpfun",
            symbol="TOKEN",
            side=TradeSide.SELL,
            quantity=5.0,
            metadata={"mint": "TokenMintAddress123"}
        )
        
        result = adapter._submit_order_live(request)
        
        assert result.symbol == "TOKEN"

    def test_submit_order_with_size_sol(self, adapter):
        """Test order with size_sol in metadata."""
        adapter._http.get.return_value = MagicMock(
            json=lambda: [],
            raise_for_status=lambda: None
        )
        
        request = TradeRequest(
            venue="pumpfun",
            symbol="",
            side=TradeSide.BUY,
            quantity=1.0,
            metadata={"token_address": "addr123", "size_sol": 0.5}
        )
        
        result = adapter._submit_order_live(request)
        
        # Symbol should be token_address when symbol is empty
        assert result.symbol == "addr123"

    def test_submit_order_with_wallet_secret(self, adapter_with_wallet):
        """Test order when wallet secret is configured."""
        adapter_with_wallet._http.get.return_value = MagicMock(
            json=lambda: {"trades": [{"priceSol": 0.003}]},
            raise_for_status=lambda: None
        )
        
        request = TradeRequest(
            venue="pumpfun",
            symbol="PUMP",
            side=TradeSide.BUY,
            quantity=1.0,
            metadata={"token_address": "wallet_test_addr"}
        )
        
        result = adapter_with_wallet._submit_order_live(request)
        
        assert result.status == "pending"
        assert "Wallet configured" in result.metadata["message"]


# =============================================================================
# Fetch Last Trade Tests
# =============================================================================

class TestFetchLastTrade:
    """Test _fetch_last_trade method."""

    def test_fetch_last_trade_dict_response(self, adapter):
        """Test fetching last trade with dict response."""
        adapter._http.get.return_value = MagicMock(
            json=lambda: {"trades": [{"priceSol": 0.0015}]},
            raise_for_status=lambda: None
        )
        
        result = adapter._fetch_last_trade("token123")
        
        assert result["price_sol"] == 0.0015
        assert "raw" in result

    def test_fetch_last_trade_list_response(self, adapter):
        """Test fetching last trade with list response."""
        adapter._http.get.return_value = MagicMock(
            json=lambda: [{"price": 0.002}],
            raise_for_status=lambda: None
        )
        
        result = adapter._fetch_last_trade("token456")
        
        assert result["price_sol"] == 0.002

    def test_fetch_last_trade_empty_trades(self, adapter):
        """Test fetching when no trades available."""
        adapter._http.get.return_value = MagicMock(
            json=lambda: {"trades": []},
            raise_for_status=lambda: None
        )
        
        result = adapter._fetch_last_trade("token789")
        
        assert result["price_sol"] == 0.0

    def test_fetch_last_trade_empty_list(self, adapter):
        """Test fetching with empty list response."""
        adapter._http.get.return_value = MagicMock(
            json=lambda: [],
            raise_for_status=lambda: None
        )
        
        result = adapter._fetch_last_trade("empty_token")
        
        assert result["price_sol"] == 0.0

    def test_fetch_last_trade_error_handling(self, adapter):
        """Test error handling in fetch."""
        adapter._http.get.side_effect = Exception("Network error")
        
        result = adapter._fetch_last_trade("error_token")
        
        assert result["price_sol"] == 0.0
        assert "error" in result

    def test_fetch_last_trade_http_error(self, adapter):
        """Test HTTP error handling."""
        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "404", request=MagicMock(), response=MagicMock()
        )
        adapter._http.get.return_value = mock_response
        
        result = adapter._fetch_last_trade("not_found_token")
        
        assert result["price_sol"] == 0.0
        assert "error" in result


# =============================================================================
# Class Attributes Tests
# =============================================================================

class TestClassAttributes:
    """Test class-level attributes."""

    def test_venue_name(self):
        assert PumpFunAdapter.venue == "pumpfun"

    def test_supports_trading(self):
        assert PumpFunAdapter.supports_trading is True
