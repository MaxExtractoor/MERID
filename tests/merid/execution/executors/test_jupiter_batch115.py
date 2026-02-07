"""Tests for merid/execution/executors/jupiter.py - Batch 115."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from merid.execution.executors.jupiter import JupiterExecutor


class TestJupiterExecutor:
    """Tests for JupiterExecutor."""

    def test_executor_initialization(self):
        executor = JupiterExecutor()
        assert executor is not None
        assert executor.venue == "jupiter"
