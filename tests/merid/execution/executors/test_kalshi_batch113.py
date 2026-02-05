"""Tests for merid/execution/executors/kalshi.py - Batch 113."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from merid.execution.executors.kalshi import KalshiExecutor


class TestKalshiExecutor:
    """Tests for KalshiExecutor."""

    def test_executor_initialization(self):
        executor = KalshiExecutor()
        assert executor is not None
        assert executor.venue == "kalshi"
