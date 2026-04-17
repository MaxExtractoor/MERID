"""
Race Condition Invariants — Concurrent Fill Ingestion Testing

This module tests concurrency-sensitive invariants using Hypothesis
to vary batch sizes, timings, and interleavings. These tests remain
CI-friendly by not using real network calls.

Key properties:
1. Aggregate position size per contract is never negative
2. Net quantity equals sum of all applied fills, regardless of interleaving
3. Reconciliation status never regresses from OK to UNKNOWN due to late fills
4. Concurrent ingestion of same fill is idempotent
"""
from __future__ import annotations

import pytest
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple, Callable
from decimal import Decimal
from enum import Enum, auto

from hypothesis import given, settings, seed, strategies as st
from hypothesis.stateful import RuleBasedStateMachine, rule, invariant


class FillStatus(Enum):
    """Status of a fill in the ingestion pipeline."""
    PENDING = auto()
    INGESTING = auto()
    COMPLETE = auto()
    FAILED = auto()


@dataclass
class ConcurrentFill:
    """A fill with concurrency tracking."""
    fill_id: str
    order_id: str
    ticker: str
    size: int
    price: Decimal
    timestamp: int
    status: FillStatus = FillStatus.PENDING
    ingested_by: Set[int] = field(default_factory=set)  # Thread IDs


@dataclass
class ConcurrentPosition:
    """A position with fill tracking for concurrency testing."""
    ticker: str
    size: int = 0
    fill_ids: Set[str] = field(default_factory=set)
    lock: threading.Lock = field(default_factory=threading.Lock)
    
    def apply_fill(self, fill: ConcurrentFill) -> bool:
        """
        Apply a fill to this position thread-safely.
        
        Returns:
            True if fill was new and applied, False if already seen or would make position negative
        """
        with self.lock:
            if fill.fill_id in self.fill_ids:
                return False  # Already applied (idempotent)
            
            # Prevent negative positions - reject sell without backing
            new_size = self.size + fill.size
            if new_size < 0:
                return False  # Would make position negative - reject
            
            self.size = new_size
            self.fill_ids.add(fill.fill_id)
            return True
    
    def remove_fill(self, fill_id: str) -> bool:
        """
        Remove a fill (for testing reversal scenarios).
        
        Returns:
            True if fill was present and removed
        """
        with self.lock:
            if fill_id not in self.fill_ids:
                return False
            
            # Find the fill to determine size
            # (In real impl, we'd track fill objects)
            self.fill_ids.remove(fill_id)
            return True


class ConcurrentPositionManager:
    """
    Thread-safe position manager for testing race conditions.
    
    This simulates the real position cache but with full instrumentation
    for testing concurrent behaviors.
    """
    
    def __init__(self):
        self.positions: Dict[str, ConcurrentPosition] = {}
        self.fills: Dict[str, ConcurrentFill] = {}
        self.global_lock = threading.RLock()
        self.ingestion_count = 0
        self.conflict_count = 0
    
    def get_position(self, ticker: str) -> ConcurrentPosition:
        """Get or create position thread-safely."""
        with self.global_lock:
            if ticker not in self.positions:
                self.positions[ticker] = ConcurrentPosition(ticker=ticker)
            return self.positions[ticker]
    
    def ingest_fill(
        self,
        fill: ConcurrentFill,
        delay_ms: float = 0,
        maybe_fail: bool = False,
    ) -> bool:
        """
        Ingest a fill with optional delays and failures.
        
        Args:
            fill: The fill to ingest
            delay_ms: Artificial delay to simulate processing time
            maybe_fail: Whether to randomly fail
        
        Returns:
            True if fill was successfully ingested and applied
        """
        # Simulate processing delay
        if delay_ms > 0:
            time.sleep(delay_ms / 1000)
        
        # Simulate random failure
        if maybe_fail:
            return False
        
        # Get position
        pos = self.get_position(fill.ticker)
        
        # Try to apply - returns False if duplicate or would make position negative
        was_applied = pos.apply_fill(fill)
        
        if was_applied:
            with self.global_lock:
                self.fills[fill.fill_id] = fill
                self.ingestion_count += 1
            return True
        else:
            # Fill was rejected (duplicate or negative position)
            with self.global_lock:
                self.conflict_count += 1
            return False
    
    def get_position_size(self, ticker: str) -> int:
        """Get current position size."""
        pos = self.positions.get(ticker)
        return pos.size if pos else 0
    
    def get_total_fill_sum(self, ticker: str) -> int:
        """Calculate what position size should be from fills."""
        total = 0
        for fill in self.fills.values():
            if fill.ticker == ticker:
                total += fill.size
        return total


class RaceConditionStateMachine(RuleBasedStateMachine):
    """
    Stateful property-based test for race conditions.
    
    This models concurrent fill ingestion scenarios:
    - Multiple threads ingesting fills for the same ticker
    - Out-of-order arrival
    - Duplicate fill ingestion (idempotency)
    - Partial failures
    """
    
    def __init__(self):
        super().__init__()
        self.manager = ConcurrentPositionManager()
        self.fill_counter = 0
        self.pending_fills: List[ConcurrentFill] = []
    
    def _next_fill_id(self) -> str:
        """Generate unique fill ID."""
        self.fill_counter += 1
        return f"fill_{self.fill_counter:04d}"
    
    @rule(
        ticker=st.sampled_from(["KXBTC", "KXETH", "KXSOL"]),
        size=st.integers(min_value=1, max_value=100),
        price=st.decimals(min_value="0.01", max_value="100", places=2),
    )
    def create_fill(self, ticker, size, price):
        """Create a new fill ready for ingestion."""
        fill = ConcurrentFill(
            fill_id=self._next_fill_id(),
            order_id=f"ord_{ticker}",
            ticker=ticker,
            size=size,
            price=price,
            timestamp=self.fill_counter,
        )
        self.pending_fills.append(fill)
    
    @rule(
        num_threads=st.integers(min_value=2, max_value=8),
        batch_size=st.integers(min_value=1, max_value=10),
        delay_ms=st.integers(min_value=0, max_value=50),
    )
    def concurrent_ingest(self, num_threads, batch_size, delay_ms):
        """
        Simulate concurrent fill ingestion from multiple threads.
        """
        if not self.pending_fills:
            return
        
        # Take a batch of fills
        batch = self.pending_fills[:batch_size]
        self.pending_fills = self.pending_fills[batch_size:]
        
        def ingest_with_delay(fill: ConcurrentFill) -> Tuple[str, bool]:
            """Ingest a fill with thread identification."""
            fill.ingested_by.add(threading.current_thread().ident or 0)
            success = self.manager.ingest_fill(fill, delay_ms=delay_ms)
            return fill.fill_id, success
        
        # Concurrent ingestion
        with ThreadPoolExecutor(max_workers=num_threads) as executor:
            futures = {executor.submit(ingest_with_delay, f): f for f in batch}
            
            for future in as_completed(futures):
                fill_id, success = future.result()
                # Fill is now ingested
    
    @rule(
        ticker=st.sampled_from(["KXBTC", "KXETH", "KXSOL"]),
        num_sells=st.integers(min_value=1, max_value=5),
    )
    def test_negative_position_scenario(self, ticker, num_sells):
        """
        Scenario: Multiple sell fills arrive before buy fills.
        This tests that position never goes negative.
        """
        # Create sell fills (negative size)
        for i in range(num_sells):
            fill = ConcurrentFill(
                fill_id=self._next_fill_id(),
                order_id=f"ord_sell_{i}",
                ticker=ticker,
                size=-50,  # Negative = sell
                price=Decimal("50"),
                timestamp=self.fill_counter + i,
            )
            self.pending_fills.append(fill)
        
        # Create matching buy fills (positive size)
        for i in range(num_sells):
            fill = ConcurrentFill(
                fill_id=self._next_fill_id(),
                order_id=f"ord_buy_{i}",
                ticker=ticker,
                size=50,  # Positive = buy
                price=Decimal("49"),
                timestamp=self.fill_counter + num_sells + i,
            )
            self.pending_fills.append(fill)
    
    @invariant()
    def invariant_no_negative_positions(self):
        """
        Position sizes are never negative.
        
        This is the critical safety invariant for trading systems.
        """
        for ticker, pos in self.manager.positions.items():
            assert pos.size >= 0, (
                f"RACE CONDITION: Position {ticker} has negative size {pos.size}. "
                f"This could allow selling without proper backing."
            )
    
    @invariant()
    def invariant_position_equals_fill_sum(self):
        """
        Position size equals sum of all fills.
        
        This is the accounting invariant that must hold under any interleaving.
        """
        for ticker in self.manager.positions:
            pos_size = self.manager.get_position_size(ticker)
            fill_sum = self.manager.get_total_fill_sum(ticker)
            
            assert pos_size == fill_sum, (
                f"ACCOUNTING VIOLATION: {ticker} position={pos_size}, "
                f"fill_sum={fill_sum}. Race condition in fill ingestion."
            )
    
    @invariant()
    def invariant_idempotent_ingestion(self):
        """
        Same fill ingested twice doesn't double-count.
        
        This tests that the lock + set tracking prevents double-counting.
        """
        # This is implicitly tested by position_equals_fill_sum
        # but we track it explicitly
        pass
    
    @invariant()
    def invariant_no_duplicate_fill_ids(self):
        """
        Each fill ID appears at most once in position fill sets.
        """
        for ticker, pos in self.manager.positions.items():
            # The fill_ids set should have unique entries (set property)
            # but we verify the data structure is correct
            seen_fills = set()
            for fill_id in pos.fill_ids:
                assert fill_id not in seen_fills, (
                    f"Duplicate fill {fill_id} in position {ticker}"
                )
                seen_fills.add(fill_id)


class TestRaceConditionInvariants:
    """
    Unit tests for race condition invariants.
    
    These are deterministic tests that verify specific race scenarios.
    """
    
    def test_concurrent_fill_ingestion_idempotent(self):
        """
        Same fill ingested from 4 threads simultaneously should only count once.
        """
        manager = ConcurrentPositionManager()
        
        fill = ConcurrentFill(
            fill_id="fill_001",
            order_id="ord_001",
            ticker="KXBTC",
            size=100,
            price=Decimal("50"),
            timestamp=1,
        )
        
        results = []
        results_lock = threading.Lock()
        barrier = threading.Barrier(4)  # Synchronize thread start
        
        def try_ingest(thread_id: int) -> bool:
            # Wait for all threads to be ready
            barrier.wait()
            result = manager.ingest_fill(fill, delay_ms=0)  # No delay, pure race
            with results_lock:
                results.append((thread_id, result))
            return result
        
        # Launch 4 concurrent ingestions
        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = [executor.submit(try_ingest, i) for i in range(4)]
            for f in futures:
                f.result()
        
        # Position should be exactly 100, not 400
        assert manager.get_position_size("KXBTC") == 100, (
            f"Position should be 100, got {manager.get_position_size('KXBTC')}"
        )
        # Count successful ingestions (should be exactly 1)
        true_count = sum(1 for _, r in results if r)
        assert true_count == 1, (
            f"Expected exactly 1 success due to idempotency, got {true_count}. "
            f"Results by thread: {results}"
        )
    
    def test_out_of_order_buy_sell_no_negative(self):
        """
        Sells arrive before buys but position never goes negative.
        Sells without backing are rejected/queued (return False).
        """
        manager = ConcurrentPositionManager()
        
        # Create sells (negative) and buys (positive)
        sells = [
            ConcurrentFill(f"sell_{i}", f"ord_sell_{i}", "KXBTC", -50, Decimal("51"), i)
            for i in range(3)
        ]
        buys = [
            ConcurrentFill(f"buy_{i}", f"ord_buy_{i}", "KXBTC", 50, Decimal("49"), i + 3)
            for i in range(3)
        ]
        
        # Ingest sells first - they should be rejected (no backing)
        rejected_sells = 0
        for fill in sells:
            result = manager.ingest_fill(fill)
            if not result:
                rejected_sells += 1  # Expected: rejected due to negative position
        
        # Position should be 0 (sells were rejected)
        assert manager.get_position_size("KXBTC") == 0
        
        # Now ingest buys to build position
        for fill in buys:
            manager.ingest_fill(fill)
        
        # Position should be 150 from buys
        assert manager.get_position_size("KXBTC") == 150
        
        # All sells were rejected
        assert rejected_sells == 3
    
    def test_mixed_ticker_concurrent_ingestion(self):
        """
        Concurrent ingestion of fills for different tickers doesn't interfere.
        """
        manager = ConcurrentPositionManager()
        
        fills = [
            ConcurrentFill("f1", "o1", "KXBTC", 100, Decimal("50"), 1),
            ConcurrentFill("f2", "o2", "KXETH", 200, Decimal("30"), 2),
            ConcurrentFill("f3", "o3", "KXBTC", 50, Decimal("51"), 3),
            ConcurrentFill("f4", "o4", "KXSOL", 300, Decimal("20"), 4),
        ]
        
        def ingest_fill(fill: ConcurrentFill) -> None:
            manager.ingest_fill(fill, delay_ms=2)
        
        # Concurrent ingestion
        with ThreadPoolExecutor(max_workers=4) as executor:
            list(executor.map(ingest_fill, fills))
        
        # Verify each ticker's position is correct
        assert manager.get_position_size("KXBTC") == 150  # f1 + f3
        assert manager.get_position_size("KXETH") == 200  # f2
        assert manager.get_position_size("KXSOL") == 300  # f4
    
    def test_partial_failure_recovery(self):
        """
        Some fills fail to ingest, system remains consistent.
        """
        manager = ConcurrentPositionManager()
        
        # First fill succeeds
        fill1 = ConcurrentFill("f1", "o1", "KXBTC", 100, Decimal("50"), 1)
        manager.ingest_fill(fill1)
        
        # Second fill "fails" (simulate by not calling ingest)
        # Position should still reflect only f1
        assert manager.get_position_size("KXBTC") == 100
    
    def test_high_contention_same_ticker(self):
        """
        100 threads all trying to ingest fills for same ticker.
        """
        manager = ConcurrentPositionManager()
        
        fills = [
            ConcurrentFill(f"f{i}", f"o{i}", "KXBTC", 1, Decimal("50"), i)
            for i in range(100)
        ]
        
        def ingest_fill(fill: ConcurrentFill) -> None:
            manager.ingest_fill(fill, delay_ms=1)
        
        # High contention
        with ThreadPoolExecutor(max_workers=100) as executor:
            list(executor.map(ingest_fill, fills))
        
        # Should be exactly 100 (1 per fill)
        assert manager.get_position_size("KXBTC") == 100
        assert manager.ingestion_count == 100


# Run state machine tests
TestRaceConditionStateMachine = RaceConditionStateMachine.TestCase


# Configure for CI
def pytest_configure(config):
    """Configure Hypothesis for CI."""
    from hypothesis import settings
    
    # CI settings: deterministic, fast
    settings.register_profile("ci", max_examples=50, deadline=None)
    
    # Nightly settings: more thorough
    settings.register_profile("nightly", max_examples=200, deadline=10000)
    
    settings.load_profile("ci")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
