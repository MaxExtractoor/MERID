"""Tests for trading/adapters/registry.py - Batch 106."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from trading.adapters.registry import register_adapter, get_adapter


class TestAdapterRegistry:
    """Tests for adapter registry functions."""

    def test_register_and_get_adapter(self):
        mock_adapter = MagicMock()
        mock_adapter.venue = "test_venue"
        register_adapter(mock_adapter)
        result = get_adapter("test_venue")
        assert result is mock_adapter

    def test_get_nonexistent_adapter(self):
        result = get_adapter("nonexistent_venue")
        assert result is None
