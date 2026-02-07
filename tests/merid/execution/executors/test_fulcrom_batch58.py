"""Tests for merid/execution/executors/fulcrom.py - Batch 58 (3-5 tests)."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from merid.execution.executors.fulcrom import FulcromExecutor


class TestFulcromExecutor:
    """Tests for FulcromExecutor (small batch)."""

    def test_venue_attribute(self):
        """Test venue class attribute."""
        assert FulcromExecutor.venue == "fulcrom"

    def test_init_default(self):
        """Test initialization with default values."""
        with patch.dict('os.environ', {}, clear=True):
            executor = FulcromExecutor()
            assert executor.venue == "fulcrom"
            assert executor.rpc_url == "https://evm-cronos.crypto.org"
            assert executor.private_key is None

    def test_init_with_env_vars(self):
        """Test initialization with environment variables."""
        env = {
            'CRONOS_RPC_URL': 'https://custom.rpc',
            'CRONOS_PRIVATE_KEY': '0xabc123'
        }
        with patch.dict('os.environ', env, clear=True):
            executor = FulcromExecutor()
            assert executor.rpc_url == 'https://custom.rpc'
            assert executor.private_key == '0xabc123'

    def test_get_auth_headers(self):
        """Test auth headers generation."""
        executor = FulcromExecutor()
        headers = executor._get_auth_headers()
        assert headers == {}
