"""Tests for merid/execution/executors/fulcrom.py - Batch 117."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from merid.execution.executors.fulcrom import FulcromExecutor


class TestFulcromExecutor:
    """Tests for FulcromExecutor."""

    def test_executor_initialization(self):
        executor = FulcromExecutor()
        assert executor is not None
        assert executor.venue == "fulcrom"
