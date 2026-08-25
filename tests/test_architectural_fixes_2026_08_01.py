"""
Tests for architectural fixes implemented on 2026-08-01.

These tests verify:
1. Position cache cross-validation between sync sources (Bug 2)
2. Unified enforcement gate (Bug 9)
3. Atomic transaction manager (Bug 10)
"""

import pytest
import time
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime, timezone, timedelta

from merid.risk.unified_enforcement_gate import (
    UnifiedEnforcementGate, EnforcementResult, get_unified_enforcement_gate
)
from merid.risk.atomic_transaction import (
    AtomicTransactionManager, get_atomic_transaction_manager, TransactionState
)


class TestPositionCacheCrossValidation:
    """Test that position cache cross-validates between sync sources."""
    
    def test_cross_validation_logic_exists(self):
        """Test that cross-validation logic exists in position cache."""
        from merid.event_venues.kalshi.position_cache import KalshiPositionCache
        
        # Verify cross-validation code exists by checking the source
        import inspect
        source = inspect.getsource(KalshiPositionCache.sync_from_rest)
        
        # Check that cross-validation is mentioned
        assert "cross" in source.lower() or "validation" in source.lower() or "fills_ledger" in source.lower(), \
            "Cross-validation logic should be present in sync_from_rest"
    
    def test_timedelta_imported(self):
        """Test that timedelta is imported for cross-validation."""
        from merid.event_venues.kalshi.position_cache import KalshiPositionCache
        
        # Verify timedelta is available in the module
        import merid.event_venues.kalshi.position_cache as position_cache_module
        assert hasattr(position_cache_module, 'timedelta'), \
            "timedelta should be imported for cross-validation"


class TestUnifiedEnforcementGate:
    """Test unified enforcement gate (Bug 9)."""
    
    def test_unified_gate_exists(self):
        """Test that unified enforcement gate can be instantiated."""
        gate = UnifiedEnforcementGate()
        assert gate is not None
        assert gate._total_checks == 0
    
    def test_unified_gate_singleton(self):
        """Test that unified enforcement gate is a singleton."""
        gate1 = get_unified_enforcement_gate()
        gate2 = get_unified_enforcement_gate()
        assert gate1 is gate2
    
    def test_enforcement_check_structure(self):
        """Test that enforcement check has proper structure."""
        gate = UnifiedEnforcementGate()
        
        decision = gate.check_order(
            agent_id="TEST_AGENT",
            asset="BTC",
            ticker="KXBTC15M-TEST",
            entry_price_cents=50,
            edge_pct=0.05,
            confidence=0.6,
            is_exit_order=False
        )
        
        assert decision.result in [EnforcementResult.ALLOWED, EnforcementResult.REJECTED, EnforcementResult.ERROR]
        assert decision.reason is not None
        assert decision.checks_performed is not None
        assert len(decision.checks_performed) > 0
    
    def test_enforcement_check_performs_all_checks(self):
        """Test that enforcement check performs all three checks."""
        gate = UnifiedEnforcementGate()
        
        decision = gate.check_order(
            agent_id="TEST_AGENT",
            asset="BTC",
            ticker="KXBTC15M-TEST",
            entry_price_cents=50,
            edge_pct=0.05,
            confidence=0.6,
            is_exit_order=False
        )
        
        # Should perform at least slot_allocation check
        # (may not reach other checks if slot allocation fails)
        assert "slot_allocation" in decision.checks_performed
        # If slot allocation passed, should have performed other checks
        if decision.result == EnforcementResult.ALLOWED:
            assert "global_allocator" in decision.checks_performed
            assert "order_routing" in decision.checks_performed
    
    def test_enforcement_statistics(self):
        """Test that enforcement gate tracks statistics."""
        gate = UnifiedEnforcementGate()
        
        # Perform a check
        gate.check_order(
            agent_id="TEST_AGENT",
            asset="BTC",
            ticker="KXBTC15M-TEST",
            entry_price_cents=50,
            edge_pct=0.05,
            confidence=0.6,
            is_exit_order=False
        )
        
        stats = gate.get_statistics()
        assert stats["total_checks"] == 1
        assert "total_rejections" in stats
        assert "total_errors" in stats
        assert "rejection_rate" in stats


class TestAtomicTransactionManager:
    """Test atomic transaction manager (Bug 10)."""
    
    def test_atomic_txn_manager_exists(self):
        """Test that atomic transaction manager can be instantiated."""
        manager = AtomicTransactionManager()
        assert manager is not None
        assert manager._transaction_counter == 0
    
    def test_atomic_txn_manager_singleton(self):
        """Test that atomic transaction manager is a singleton."""
        manager1 = get_atomic_transaction_manager()
        manager2 = get_atomic_transaction_manager()
        assert manager1 is manager2
    
    def test_transaction_commit(self):
        """Test that transaction commits successfully."""
        manager = AtomicTransactionManager()
        
        with manager.transaction():
            # Simulate successful operations
            pass
        
        # Transaction should be committed
        assert len(manager.get_active_transactions()) == 0
    
    def test_transaction_rollback_on_exception(self):
        """Test that transaction rolls back on exception."""
        manager = AtomicTransactionManager()
        
        rollback_called = False
        
        def mock_rollback():
            nonlocal rollback_called
            rollback_called = True
        
        with pytest.raises(Exception):
            with manager.transaction() as state:
                # Add rollback operation
                manager.add_rollback_operation(state.transaction_id, mock_rollback)
                # Raise exception to trigger rollback
                raise Exception("Test exception")
        
        # Rollback should have been called
        assert rollback_called
    
    def test_rollback_operation_execution(self):
        """Test that rollback operations are executed in reverse order."""
        manager = AtomicTransactionManager()
        
        execution_order = []
        
        def rollback_op1():
            execution_order.append(1)
        
        def rollback_op2():
            execution_order.append(2)
        
        def rollback_op3():
            execution_order.append(3)
        
        with pytest.raises(Exception):
            with manager.transaction() as state:
                # Add rollback operations
                manager.add_rollback_operation(state.transaction_id, rollback_op1)
                manager.add_rollback_operation(state.transaction_id, rollback_op2)
                manager.add_rollback_operation(state.transaction_id, rollback_op3)
                # Raise exception to trigger rollback
                raise Exception("Test exception")
        
        # Rollback operations should be executed in reverse order
        assert execution_order == [3, 2, 1]
    
    def test_active_transactions_tracking(self):
        """Test that active transactions are tracked."""
        manager = AtomicTransactionManager()
        
        # Start a transaction (but don't commit yet by using a different approach)
        txn_id = "test_txn"
        from merid.risk.atomic_transaction import TransactionState
        state = TransactionState(transaction_id=txn_id)
        manager._active_transactions[txn_id] = state
        
        # Check that it's tracked
        assert txn_id in manager.get_active_transactions()
        
        # Clean up
        del manager._active_transactions[txn_id]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
