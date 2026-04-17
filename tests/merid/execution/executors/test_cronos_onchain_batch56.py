"""Tests for merid/execution/executors/cronos_onchain.py - Batch 56 (3-5 tests)."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from merid.execution.executors.cronos_onchain import CronosOnchainExecutor


class TestCronosOnchainExecutor:
    """Tests for CronosOnchainExecutor (small batch)."""

    def test_venue_attribute(self):
        """Test venue class attribute."""
        assert CronosOnchainExecutor.venue == "cronos_onchain"

    def test_init_default(self):
        """Test initialization with default values."""
        with patch.dict('os.environ', {}, clear=True):
            executor = CronosOnchainExecutor()
            assert executor.venue == "cronos_onchain"
            assert executor.private_key is None

    def test_init_with_private_key(self):
        """Test initialization with private key from env."""
        with patch.dict('os.environ', {'CRONOS_PRIVATE_KEY': '0xabc123'}, clear=True):
            executor = CronosOnchainExecutor()
            assert executor.private_key == '0xabc123'

    def test_get_auth_headers(self):
        """Test auth headers generation."""
        executor = CronosOnchainExecutor()
        headers = executor._get_auth_headers()
        assert headers == {"Content-Type": "application/json"}

    @pytest.mark.asyncio
    async def test_fetch_price_known_pair(self):
        """Test fetching price for known token pair."""
        executor = CronosOnchainExecutor()
        price = await executor._fetch_price("ETH", "USDC")
        assert price == 3000.0

    @pytest.mark.asyncio
    async def test_fetch_price_unknown_pair(self):
        """Test fetching price for unknown token pair."""
        executor = CronosOnchainExecutor()
        price = await executor._fetch_price("UNKNOWN", "TOKEN")
        assert price == 1.0
