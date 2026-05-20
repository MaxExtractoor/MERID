"""Tests for trading/merid_adapter.py - Batch 91."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from trading.merid_adapter import MeridExecutionAdapter


class TestMeridExecutionAdapter:
    """Tests for MeridExecutionAdapter."""

    def test_adapter_initialization_default(self):
        adapter = MeridExecutionAdapter()
        assert adapter.execution_service_url == "http://127.0.0.1:8011"
        assert adapter.account_id == "merid_sim_account"
        assert adapter._connected is False

    def test_adapter_initialization_custom_url(self):
        adapter = MeridExecutionAdapter(execution_service_url="http://localhost:9000")
        assert adapter.execution_service_url == "http://localhost:9000"

    def test_adapter_not_connected_initially(self):
        adapter = MeridExecutionAdapter()
        assert adapter._connected is False
        assert adapter.session is None
