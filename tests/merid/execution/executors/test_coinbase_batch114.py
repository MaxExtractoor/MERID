"""Tests for merid/execution/executors/coinbase.py - Batch 114."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from merid.execution.executors.coinbase import CoinbaseExecutor


class TestCoinbaseExecutor:
    """Tests for CoinbaseExecutor."""

    def test_executor_initialization(self):
        executor = CoinbaseExecutor()
        assert executor is not None
        assert executor.venue == "coinbase"
