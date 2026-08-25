"""
Atomic Transaction Manager for Risk Enforcement.

This module implements atomic transactions with rollback for risk enforcement
to prevent partial state updates and ensure consistency.

CRITICAL FIX (2026-08-01): Addresses Bug 10 - No atomic transactions across enforcement layers.
"""

import threading
from dataclasses import dataclass, field
from typing import Callable, Optional, List, Any
from contextlib import contextmanager

from utils.logger import get_logger

logger = get_logger("merid.risk.atomic_transaction")


@dataclass
class TransactionState:
    """State of an atomic transaction."""
    transaction_id: str
    operations: List[dict] = field(default_factory=list)
    rollback_operations: List[Callable] = field(default_factory=list)
    committed: bool = False
    rolled_back: bool = False


class AtomicTransactionManager:
    """
    Manager for atomic transactions with rollback capability.
    
    This ensures that all operations in a transaction either succeed together
    or are rolled back together, preventing partial state updates.
    
    CRITICAL FIX (2026-08-01): Addresses Bug 10 - No atomic transactions across enforcement layers.
    """
    
    def __init__(self):
        self._lock = threading.RLock()
        self._active_transactions: Dict[str, TransactionState] = {}
        self._transaction_counter = 0
        
        logger.info("[ATOMIC-TXN] Initialized atomic transaction manager")
    
    @contextmanager
    def transaction(self, transaction_id: Optional[str] = None):
        """
        Context manager for atomic transaction.
        
        Usage:
            with txn_manager.transaction():
                # Perform operations
                slot_allocator.allocate(...)
                global_allocator.allocate(...)
                # If any operation fails, all are rolled back
        
        Args:
            transaction_id: Optional transaction ID (auto-generated if None)
        """
        if transaction_id is None:
            with self._lock:
                self._transaction_counter += 1
                transaction_id = f"txn_{self._transaction_counter}"
        
        state = TransactionState(transaction_id=transaction_id)
        
        with self._lock:
            self._active_transactions[transaction_id] = state
        
        try:
            yield state
            
            # Commit if no exception occurred
            with self._lock:
                state.committed = True
                del self._active_transactions[transaction_id]
                logger.debug("[ATOMIC-TXN] Transaction %s committed", transaction_id)
                
        except Exception as e:
            # Rollback on exception
            logger.error("[ATOMIC-TXN] Transaction %s failed, rolling back: %s", transaction_id, e)
            self._rollback(transaction_id)
            raise
    
    def _rollback(self, transaction_id: str) -> None:
        """Rollback a transaction by executing rollback operations."""
        with self._lock:
            if transaction_id not in self._active_transactions:
                logger.warning("[ATOMIC-TXN] Transaction %s not found for rollback", transaction_id)
                return
            
            state = self._active_transactions[transaction_id]
            
            # Execute rollback operations in reverse order
            for rollback_op in reversed(state.rollback_operations):
                try:
                    rollback_op()
                    logger.debug("[ATOMIC-TXN] Executed rollback operation for %s", transaction_id)
                except Exception as e:
                    logger.error("[ATOMIC-TXN] Rollback operation failed for %s: %s", transaction_id, e)
            
            state.rolled_back = True
            del self._active_transactions[transaction_id]
            logger.info("[ATOMIC-TXN] Transaction %s rolled back", transaction_id)
    
    def add_rollback_operation(self, transaction_id: str, rollback_op: Callable) -> None:
        """
        Add a rollback operation to the current transaction.
        
        Args:
            transaction_id: Transaction ID
            rollback_op: Callable to execute on rollback
        """
        with self._lock:
            if transaction_id in self._active_transactions:
                self._active_transactions[transaction_id].rollback_operations.append(rollback_op)
            else:
                logger.warning("[ATOMIC-TXN] Transaction %s not found, cannot add rollback operation", transaction_id)
    
    def get_active_transactions(self) -> List[str]:
        """Get list of active transaction IDs."""
        with self._lock:
            return list(self._active_transactions.keys())


# Singleton instance
_atomic_txn_manager: Optional[AtomicTransactionManager] = None


def get_atomic_transaction_manager() -> AtomicTransactionManager:
    """Get the singleton atomic transaction manager instance."""
    global _atomic_txn_manager
    if _atomic_txn_manager is None:
        _atomic_txn_manager = AtomicTransactionManager()
    return _atomic_txn_manager
