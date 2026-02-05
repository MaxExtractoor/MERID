"""Tests for trading/adapters/kalshi.py - Batch 108."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from trading.adapters.kalshi import KalshiPredictionAdapter


class TestKalshiPredictionAdapter:
    """Tests for KalshiPredictionAdapter."""

    def test_adapter_initialization(self):
        adapter = KalshiPredictionAdapter()
        assert adapter is not None
        assert adapter.venue == "kalshi"
