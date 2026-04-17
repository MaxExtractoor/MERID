"""Tests for trading adapters pumpfun module - Batch 44 Coverage."""
import pytest
from unittest.mock import MagicMock, patch
import os

from trading.adapters.pumpfun import PumpFunAdapter
from trading.adapters.base import TradeRequest, TradeSide, OrderType


class TestPumpFunAdapter:
    """Tests for PumpFunAdapter class."""

    @pytest.fixture
    def adapter(self):
        with patch.dict(os.environ, {}, clear=True):
            return PumpFunAdapter()

    @pytest.fixture
    def adapter_with_wallet(self):
        env_vars = {
            "PUMPFUN_WALLET_SECRET": "test_secret_key",
        }
        with patch.dict(os.environ, env_vars, clear=True):
            return PumpFunAdapter()

    def test_initialization_default(self, adapter):
        assert adapter.venue == "pumpfun"
        assert adapter.supports_trading is True
        assert adapter.use_mock is False
        assert adapter.api_base == "https://pump.fun/api"
        assert adapter.wallet_secret is None

    def test_initialization_custom_api_base(self):
        env_vars = {
            "PUMPFUN_API_BASE": "https://custom.pump.fun/api",
        }
        with patch.dict(os.environ, env_vars, clear=True):
            adapter = PumpFunAdapter()
            assert adapter.api_base == "https://custom.pump.fun/api"

    def test_initialization_with_wallet(self, adapter_with_wallet):
        assert adapter_with_wallet.wallet_secret == "test_secret_key"

    def test_submit_order_live_no_token_address(self, adapter):
        """Test that order without token_address raises error."""
        request = TradeRequest(
            venue="pumpfun",
            symbol="TEST",
            side=TradeSide.BUY,
            quantity=1.0,
            order_type=OrderType.MARKET,
            metadata={},  # No token_address
        )

        with pytest.raises(RuntimeError, match="token_address"):
            adapter._submit_order_live(request)

    def test_submit_order_live_simulation_mode(self, adapter):
        """Test order submission in simulation mode (no wallet)."""
        with patch.object(adapter, '_fetch_last_trade', return_value={"price_sol": 0.5}):
            request = TradeRequest(
                venue="pumpfun",
                symbol="TEST",
                side=TradeSide.BUY,
                quantity=1.0,
                order_type=OrderType.MARKET,
                metadata={"token_address": "abc123", "size_sol": 2.0},
            )

            result = adapter._submit_order_live(request)

            assert result.venue == "pumpfun"
            assert result.symbol == "TEST"
            assert result.side == TradeSide.BUY
            assert result.quantity == 1.0
            assert result.executed_price == 0.5
            assert result.status == "simulated"
            assert "token_address" in result.metadata
            assert result.metadata["token_address"] == "abc123"
            assert "Simulation only" in result.metadata["message"]

    def test_submit_order_live_pending_mode(self, adapter_with_wallet):
        """Test order submission when wallet is configured."""
        with patch.object(adapter_with_wallet, '_fetch_last_trade', return_value={"price_sol": 0.75}):
            request = TradeRequest(
                venue="pumpfun",
                symbol="PEPE",
                side=TradeSide.SELL,
                quantity=0.5,
                order_type=OrderType.MARKET,
                metadata={"token_address": "xyz789", "mint": "xyz789"},
            )

            result = adapter_with_wallet._submit_order_live(request)

            assert result.status == "pending"
            assert "Wallet configured" in result.metadata["message"]

    def test_submit_order_live_uses_mint(self, adapter):
        """Test that order can use 'mint' instead of 'token_address'."""
        with patch.object(adapter, '_fetch_last_trade', return_value={"price_sol": 1.0}):
            request = TradeRequest(
                venue="pumpfun",
                symbol="DOGE",
                side=TradeSide.BUY,
                quantity=1.0,
                order_type=OrderType.MARKET,
                metadata={"mint": "mint_address_123"},
            )

            result = adapter._submit_order_live(request)

            assert result.metadata["token_address"] == "mint_address_123"

    def test_submit_order_live_size_from_quantity(self, adapter):
        """Test that size_sol falls back to quantity if not in metadata."""
        with patch.object(adapter, '_fetch_last_trade', return_value={"price_sol": 0.1}):
            request = TradeRequest(
                venue="pumpfun",
                symbol="SHIB",
                side=TradeSide.BUY,
                quantity=5.0,
                order_type=OrderType.MARKET,
                metadata={"token_address": "shib_token"},
            )

            # size_sol should default to quantity (5.0)
            result = adapter._submit_order_live(request)
            assert result.status == "simulated"

    def test_submit_order_live_symbol_fallback(self, adapter):
        """Test that symbol falls back to token_address."""
        with patch.object(adapter, '_fetch_last_trade', return_value={"price_sol": 0.25}):
            request = TradeRequest(
                venue="pumpfun",
                symbol=None,  # No symbol provided
                side=TradeSide.BUY,
                quantity=1.0,
                order_type=OrderType.MARKET,
                metadata={"token_address": "fallback_token"},
            )

            result = adapter._submit_order_live(request)
            assert result.symbol == "fallback_token"

    def test_fetch_last_trade_dict_response(self, adapter):
        """Test _fetch_last_trade with dict response."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "trades": [{"priceSol": 0.5, "timestamp": 1234567890}]
        }
        mock_response.raise_for_status.return_value = None

        with patch.object(adapter._http, 'get', return_value=mock_response):
            result = adapter._fetch_last_trade("token_123")

            assert result["price_sol"] == 0.5
            assert "raw" in result

    def test_fetch_last_trade_list_response(self, adapter):
        """Test _fetch_last_trade with list response."""
        mock_response = MagicMock()
        mock_response.json.return_value = [
            {"price": 0.75, "timestamp": 1234567890}
        ]
        mock_response.raise_for_status.return_value = None

        with patch.object(adapter._http, 'get', return_value=mock_response):
            result = adapter._fetch_last_trade("token_456")

            assert result["price_sol"] == 0.75

    def test_fetch_last_trade_empty_response(self, adapter):
        """Test _fetch_last_trade with empty response."""
        mock_response = MagicMock()
        mock_response.json.return_value = {"trades": []}
        mock_response.raise_for_status.return_value = None

        with patch.object(adapter._http, 'get', return_value=mock_response):
            result = adapter._fetch_last_trade("token_789")

            assert result["price_sol"] == 0.0

    def test_fetch_last_trade_error(self, adapter):
        """Test _fetch_last_trade with network error."""
        with patch.object(adapter._http, 'get', side_effect=Exception("Network error")):
            result = adapter._fetch_last_trade("token_error")

            assert result["price_sol"] == 0.0
            assert "error" in result

    def test_fetch_last_trade_http_error(self, adapter):
        """Test _fetch_last_trade with HTTP error response."""
        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = Exception("404 Not Found")

        with patch.object(adapter._http, 'get', return_value=mock_response):
            result = adapter._fetch_last_trade("token_notfound")

            assert result["price_sol"] == 0.0
            assert "error" in result

    def test_register_adapter(self):
        """Test that adapter is registered on import."""
        from trading.adapters import registry
        # Force re-registration since other tests may have cleared the registry
        import importlib
        import trading.adapters.pumpfun as pumpfun_module
        importlib.reload(pumpfun_module)
        # The adapter should be registered when the module is imported
        assert "pumpfun" in registry._adapters
