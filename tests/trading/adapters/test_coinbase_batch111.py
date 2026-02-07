"""Tests for trading/adapters/coinbase.py - Batch 111."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from trading.adapters.coinbase import CoinbaseSpotAdapter


class TestCoinbaseSpotAdapter:
    """Tests for CoinbaseSpotAdapter."""

    def test_adapter_initialization(self):
        adapter = CoinbaseSpotAdapter()
        assert adapter is not None
        assert adapter.venue == "coinbase"
