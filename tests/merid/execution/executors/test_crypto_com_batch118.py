"""Tests for merid/execution/executors/crypto_com.py - Batch 118."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from merid.execution.executors.crypto_com import CryptoComExecutor


class TestCryptoComExecutor:
    """Tests for CryptoComExecutor."""

    def test_executor_initialization(self):
        executor = CryptoComExecutor()
        assert executor is not None
        assert executor.venue == "crypto_com"
