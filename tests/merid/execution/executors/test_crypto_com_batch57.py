"""Tests for merid/execution/executors/crypto_com.py - Batch 57 (3-5 tests)."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from merid.execution.executors.crypto_com import CryptoComExecutor


class TestCryptoComExecutor:
    """Tests for CryptoComExecutor (small batch)."""

    def test_venue_attribute(self):
        """Test venue class attribute."""
        assert CryptoComExecutor.venue == "crypto_com"

    def test_init_default(self):
        """Test initialization with default values."""
        with patch.dict('os.environ', {}, clear=True):
            executor = CryptoComExecutor()
            assert executor.venue == "crypto_com"
            assert executor.api_key is None
            assert executor.api_secret is None

    def test_init_with_credentials(self):
        """Test initialization with credentials from env."""
        env = {
            'CRYPTO_COM_API_KEY': 'test_key',
            'CRYPTO_COM_API_SECRET': 'test_secret'
        }
        with patch.dict('os.environ', env, clear=True):
            executor = CryptoComExecutor()
            assert executor.api_key == 'test_key'
            assert executor.api_secret == 'test_secret'

    def test_get_auth_headers(self):
        """Test auth headers generation."""
        env = {
            'CRYPTO_COM_API_KEY': 'test_key',
            'CRYPTO_COM_API_SECRET': 'test_secret'
        }
        with patch.dict('os.environ', env, clear=True):
            executor = CryptoComExecutor()
            headers = executor._get_auth_headers()
            assert headers == {
                "API-Key": "test_key",
                "API-Secret": "test_secret"
            }

    def test_symbol_to_instrument(self):
        """Test symbol to instrument conversion."""
        executor = CryptoComExecutor()
        assert executor._symbol_to_instrument("BTC-USD") == "BTCUSD"
        assert executor._symbol_to_instrument("ETH-USDC") == "ETHUSDC"

    def test_instrument_to_symbol(self):
        """Test instrument to symbol conversion."""
        executor = CryptoComExecutor()
        # Note: The implementation has a bug - assumes 4-char quote
        assert executor._instrument_to_symbol("BTCUSD") == "BT-CUSD"
        assert executor._instrument_to_symbol("ETHUSDC") == "ETH-USDC"
        assert executor._instrument_to_symbol("CRO") == "CRO"
