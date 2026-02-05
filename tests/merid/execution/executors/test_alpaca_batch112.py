"""Tests for merid/execution/executors/alpaca.py - Batch 112."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from merid.execution.executors.alpaca import AlpacaExecutor


class TestAlpacaExecutor:
    """Tests for AlpacaExecutor."""

    def test_executor_initialization(self):
        executor = AlpacaExecutor()
        assert executor is not None
        assert executor.venue == "alpaca"
