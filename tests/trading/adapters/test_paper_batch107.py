"""Tests for trading/adapters/paper.py - Batch 107."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from trading.adapters.paper import PaperTradingAdapter


class TestPaperTradingAdapter:
    """Tests for PaperTradingAdapter."""

    def test_adapter_initialization(self):
        adapter = PaperTradingAdapter()
        assert adapter is not None
        assert adapter.venue == "paper"
