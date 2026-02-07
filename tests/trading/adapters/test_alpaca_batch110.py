"""Tests for trading/adapters/alpaca.py - Batch 110."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from trading.adapters.alpaca import AlpacaEquitiesAdapter


class TestAlpacaEquitiesAdapter:
    """Tests for AlpacaEquitiesAdapter."""

    def test_adapter_initialization(self):
        adapter = AlpacaEquitiesAdapter()
        assert adapter is not None
        assert adapter.venue == "alpaca"
