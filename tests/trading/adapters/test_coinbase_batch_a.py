"""Tests for trading/adapters/coinbase.py - Batch A."""
import pytest
from unittest.mock import patch, MagicMock

from trading.adapters.coinbase import CoinbaseSpotAdapter


class TestCoinbaseSpotAdapter:
    """Tests for CoinbaseSpotAdapter."""

    def test_adapter_properties(self):
        with patch.dict('os.environ', {'MERID_COINBASE_API_KEY': 'test_key', 'MERID_COINBASE_API_SECRET': 'test_secret'}):
            with patch.object(CoinbaseSpotAdapter, '_build_exchange', return_value=None):
                adapter = CoinbaseSpotAdapter()
                assert adapter.venue == "coinbase"
                assert adapter.supports_trading is True
                assert adapter.exchange_id == "coinbasepro"

    def test_adapter_with_custom_exchange_id(self):
        with patch.dict('os.environ', {'MERID_COINBASE_API_KEY': 'test_key', 'MERID_COINBASE_API_SECRET': 'test_secret'}):
            with patch.object(CoinbaseSpotAdapter, '_build_exchange', return_value=None):
                adapter = CoinbaseSpotAdapter(exchange_id="coinbase")
                assert adapter.exchange_id == "coinbase"

    def test_adapter_env_vars(self):
        with patch.dict('os.environ', {
            'MERID_COINBASE_API_KEY': 'my_key',
            'MERID_COINBASE_API_SECRET': 'my_secret',
            'MERID_COINBASE_EXCHANGE_ID': 'coinbase',
            'MERID_COINBASE_API_PASSPHRASE': 'my_passphrase'
        }):
            with patch.object(CoinbaseSpotAdapter, '_build_exchange', return_value=None):
                adapter = CoinbaseSpotAdapter()
                assert adapter.api_key == "my_key"
                assert adapter.api_secret == "my_secret"
                assert adapter.exchange_id == "coinbase"
                assert adapter.passphrase == "my_passphrase"
