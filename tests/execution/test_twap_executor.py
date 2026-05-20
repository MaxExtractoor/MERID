"""Tests for TWAP Executor."""

import pytest
from datetime import datetime, timezone, timedelta
from execution.twap_executor import (
    TWAPExecutor,
    get_twap_executor,
    TWAPOrder,
    TWAPSlice,
    TWAPStatus,
    TWAPSliceStatus,
    TWAPConfig
)


class TestTWAPExecutor:
    """Test suite for TWAPExecutor."""
    
    def test_singleton(self):
        """Test that TWAPExecutor is a singleton."""
        executor1 = get_twap_executor()
        executor2 = get_twap_executor()
        assert executor1 is executor2
    
    def test_initialization(self):
        """Test executor initialization."""
        executor = get_twap_executor()
        summary = executor.get_summary()
        # Executor may not be running immediately after initialization
        assert "running" in summary
    
    def test_should_use_twap(self):
        """Test TWAP threshold logic."""
        executor = get_twap_executor()
        assert executor.should_use_twap(100) is True
        assert executor.should_use_twap(10) is False
    
    def test_submit_twap_order(self):
        """Test TWAP order submission."""
        executor = get_twap_executor()
        order = executor.submit_twap_order(
            ticker="KXBTC15M-TEST",
            side="yes",
            total_contracts=100,
            duration_minutes=15
        )
        assert isinstance(order, TWAPOrder)
        assert order.ticker == "KXBTC15M-TEST"
        assert order.total_contracts == 100
        # Order status may be pending or executing depending on timing
        assert order.status in [TWAPStatus.PENDING, TWAPStatus.EXECUTING]
        assert len(order.slices) > 0
    
    def test_slice_creation(self):
        """Test slice creation logic."""
        executor = get_twap_executor()
        order = executor.submit_twap_order(
            ticker="KXBTC15M-TEST",
            side="yes",
            total_contracts=100,
            duration_minutes=15
        )
        total_slice_contracts = sum(s.contracts for s in order.slices)
        assert total_slice_contracts == order.total_contracts
    
    def test_get_order(self):
        """Test order retrieval."""
        executor = get_twap_executor()
        order = executor.submit_twap_order(
            ticker="KXBTC15M-TEST",
            side="yes",
            total_contracts=100
        )
        retrieved = executor.get_order(order.order_id)
        assert retrieved is not None
        assert retrieved.order_id == order.order_id
    
    def test_get_active_orders(self):
        """Test active orders retrieval."""
        executor = get_twap_executor()
        executor.submit_twap_order(
            ticker="KXBTC15M-TEST",
            side="yes",
            total_contracts=100
        )
        active = executor.get_active_orders()
        assert len(active) >= 1
    
    def test_cancel_order(self):
        """Test order cancellation."""
        executor = get_twap_executor()
        order = executor.submit_twap_order(
            ticker="KXBTC15M-TEST",
            side="yes",
            total_contracts=100
        )
        cancelled = executor.cancel_order(order.order_id)
        assert cancelled is True
    
    def test_config(self):
        """Test configuration management."""
        executor = get_twap_executor()
        config = executor.get_config()
        assert isinstance(config, TWAPConfig)
        assert config.min_contracts_for_twap == 50
    
    def test_summary(self):
        """Test summary generation."""
        executor = get_twap_executor()
        summary = executor.get_summary()
        assert "running" in summary
        assert "active_orders" in summary
        assert "config" in summary


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
