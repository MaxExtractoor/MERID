"""Tests for trading/adapters/registry.py."""
import pytest
from trading.adapters.registry import (
    register_adapter, get_adapter, list_adapters, clear_adapters, _adapters
)
from trading.adapters.base import TradingVenueAdapterBase


class MockAdapter(TradingVenueAdapterBase):
    """Mock adapter for testing."""
    venue = "mock"
    supported_assets = ("BTC",)
    supports_trading = True

    def _get_balances_live(self):
        return []

    def _get_positions_live(self):
        return []

    def _submit_order_live(self, request):
        from trading.adapters.base import OrderResult
        return OrderResult(
            venue=self.venue,
            symbol=request.symbol,
            side=request.side,
            quantity=request.quantity,
            executed_price=100.0,
            status="filled"
        )

    def _cancel_order_live(self, venue_order_id):
        return True


class TestRegisterAdapter:
    """Test register_adapter function."""

    def setup_method(self):
        """Clear registry before each test."""
        clear_adapters()

    def test_register_adapter(self):
        """Test registering an adapter."""
        adapter = MockAdapter()
        register_adapter(adapter)
        assert "mock" in _adapters
        assert _adapters["mock"] is adapter

    def test_register_replaces_existing(self):
        """Test registering replaces existing adapter."""
        adapter1 = MockAdapter()
        register_adapter(adapter1)

        # Create another adapter with same venue
        adapter2 = MockAdapter()
        register_adapter(adapter2)

        assert _adapters["mock"] is adapter2


class TestGetAdapter:
    """Test get_adapter function."""

    def setup_method(self):
        """Clear registry before each test."""
        clear_adapters()

    def test_get_existing_adapter(self):
        """Test getting an existing adapter."""
        adapter = MockAdapter()
        register_adapter(adapter)

        result = get_adapter("mock")
        assert result is adapter

    def test_get_nonexistent_adapter(self):
        """Test getting non-existent adapter returns None."""
        result = get_adapter("nonexistent")
        assert result is None


class TestListAdapters:
    """Test list_adapters function."""

    def setup_method(self):
        """Clear registry before each test."""
        clear_adapters()

    def test_list_empty(self):
        """Test listing adapters when empty."""
        result = list_adapters()
        assert result == {}

    def test_list_with_adapters(self):
        """Test listing adapters."""
        adapter1 = MockAdapter()
        adapter1.venue = "venue1"
        register_adapter(adapter1)

        adapter2 = MockAdapter()
        adapter2.venue = "venue2"
        register_adapter(adapter2)

        result = list_adapters()
        assert "venue1" in result
        assert "venue2" in result
        assert len(result) == 2

    def test_list_returns_copy(self):
        """Test list_adapters returns a copy."""
        adapter = MockAdapter()
        register_adapter(adapter)

        result = list_adapters()
        result.clear()  # Modify the returned dict

        # Original should be unchanged
        assert "mock" in _adapters


class TestClearAdapters:
    """Test clear_adapters function."""

    def test_clear_adapters(self):
        """Test clearing all adapters."""
        adapter = MockAdapter()
        register_adapter(adapter)
        assert len(_adapters) > 0

        clear_adapters()
        assert len(_adapters) == 0
