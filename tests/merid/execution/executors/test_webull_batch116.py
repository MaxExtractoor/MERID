"""Tests for merid/execution/executors/webull.py - Batch 116."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from merid.execution.executors.webull import WebullExecutor


class TestWebullExecutor:
    """Tests for WebullExecutor."""

    def test_executor_initialization(self):
        executor = WebullExecutor()
        assert executor is not None
        assert executor.venue == "webull"
