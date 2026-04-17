"""Tests for trading/polymarket_trading_layer.py - Batch 100."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from trading.polymarket_trading_layer import ChainlinkOracle


class TestChainlinkOracle:
    """Tests for ChainlinkOracle."""

    def test_oracle_initialization(self):
        oracle = ChainlinkOracle()
        assert oracle is not None
        assert oracle.network == "polygon"
