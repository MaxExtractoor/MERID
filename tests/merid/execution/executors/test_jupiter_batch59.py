"""Tests for merid/execution/executors/jupiter.py - Batch 59 (3-5 tests)."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from merid.execution.executors.jupiter import JupiterExecutor


class TestJupiterExecutor:
    """Tests for JupiterExecutor (small batch)."""

    def test_venue_attribute(self):
        """Test venue class attribute."""
        assert JupiterExecutor.venue == "jupiter"

    def test_init_default(self):
        """Test initialization with default values."""
        with patch.dict('os.environ', {}, clear=True):
            executor = JupiterExecutor()
            assert executor.venue == "jupiter"
            assert executor.rpc_url == "https://api.mainnet-beta.solana.com"
            assert executor.private_key is None
            assert executor.public_key is None

    def test_init_with_env_vars(self):
        """Test initialization with environment variables."""
        env = {
            'SOLANA_RPC_URL': 'https://custom.solana',
            'SOLANA_PRIVATE_KEY': 'priv_key',
            'SOLANA_PUBLIC_KEY': 'pub_key'
        }
        with patch.dict('os.environ', env, clear=True):
            executor = JupiterExecutor()
            assert executor.rpc_url == 'https://custom.solana'
            assert executor.private_key == 'priv_key'
            assert executor.public_key == 'pub_key'

    def test_get_auth_headers(self):
        """Test auth headers generation."""
        executor = JupiterExecutor()
        headers = executor._get_auth_headers()
        assert headers == {}

    def test_symbol_to_mints_known(self):
        """Test symbol to mints conversion for known pairs."""
        executor = JupiterExecutor()
        sol, usdc = executor._symbol_to_mints("SOL-USDC")
        assert sol == "So11111111111111111111111111111111111111112"
        assert usdc == "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"

    def test_symbol_to_mints_unknown(self):
        """Test symbol to mints conversion for unknown pairs."""
        executor = JupiterExecutor()
        result = executor._symbol_to_mints("UNKNOWN-PAIR")
        assert result == ("", "")
