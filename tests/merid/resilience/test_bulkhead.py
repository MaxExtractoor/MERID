"""Tests for bulkhead pattern implementation."""

import asyncio
import pytest

from merid.resilience.bulkhead import (
    Bulkhead,
    BulkheadFullError,
    BulkheadStats,
    get_bulkhead,
    get_all_bulkheads,
    reset_all_bulkheads,
)


class TestBulkhead:
    """Tests for Bulkhead class."""
    
    @pytest.fixture
    def bulkhead(self):
        """Create bulkhead for testing."""
        return Bulkhead(
            name="test",
            max_concurrent=2,
            max_queued=3,
            timeout=1.0,
        )
    
    def test_initial_state(self, bulkhead):
        """Bulkhead starts with no active operations."""
        assert bulkhead.active_count == 0
        assert bulkhead.queued_count == 0
        assert bulkhead.available_slots == 2
        assert bulkhead.available_queue == 3
        assert not bulkhead.is_full()
    
    @pytest.mark.asyncio
    async def test_acquire_and_release(self, bulkhead):
        """Basic acquire and release cycle."""
        wait_ms = await bulkhead.acquire()
        
        assert bulkhead.active_count == 1
        assert wait_ms >= 0
        
        await bulkhead.release(success=True, exec_ms=10.0)
        
        assert bulkhead.active_count == 0
    
    @pytest.mark.asyncio
    async def test_context_manager(self, bulkhead):
        """Bulkhead works as async context manager."""
        assert bulkhead.active_count == 0
        
        async with bulkhead:
            assert bulkhead.active_count == 1
        
        assert bulkhead.active_count == 0
    
    @pytest.mark.asyncio
    async def test_max_concurrent_enforced(self, bulkhead):
        """Cannot exceed max concurrent operations."""
        # Acquire both slots
        await bulkhead.acquire()
        await bulkhead.acquire()
        
        assert bulkhead.active_count == 2
        assert bulkhead.available_slots == 0
        
        # Third acquire should queue (with timeout)
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(bulkhead.acquire(), timeout=0.1)
    
    @pytest.mark.asyncio
    async def test_queue_full_raises_error(self, bulkhead):
        """BulkheadFullError raised when queue is full."""
        # Fill up concurrent slots
        await bulkhead.acquire()
        await bulkhead.acquire()
        
        # Fill up queue (these will block waiting)
        tasks = []
        for _ in range(3):
            task = asyncio.create_task(bulkhead.acquire())
            tasks.append(task)
            await asyncio.sleep(0.01)  # Let task start
        
        # Queue is now full, next should raise
        with pytest.raises(BulkheadFullError) as exc_info:
            await bulkhead.acquire()
        
        assert exc_info.value.name == "test"
        assert exc_info.value.queued == 3
        
        # Cleanup
        await bulkhead.release()
        await bulkhead.release()
        for task in tasks:
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, asyncio.TimeoutError):
                pass
    
    @pytest.mark.asyncio
    async def test_success_tracking(self, bulkhead):
        """Successful operations are tracked."""
        async with bulkhead:
            pass
        
        stats = bulkhead.get_stats()
        assert stats.total_completed == 1
        assert stats.total_failed == 0
    
    @pytest.mark.asyncio
    async def test_failure_tracking(self, bulkhead):
        """Failed operations are tracked."""
        try:
            async with bulkhead:
                raise ValueError("Test error")
        except ValueError:
            pass
        
        stats = bulkhead.get_stats()
        assert stats.total_completed == 0
        assert stats.total_failed == 1
    
    @pytest.mark.asyncio
    async def test_stats_collection(self, bulkhead):
        """Statistics are collected correctly."""
        # Run a few operations
        for _ in range(3):
            async with bulkhead:
                await asyncio.sleep(0.01)
        
        stats = bulkhead.get_stats()
        
        assert stats.name == "test"
        assert stats.max_concurrent == 2
        assert stats.max_queued == 3
        assert stats.total_accepted == 3
        assert stats.total_completed == 3
        assert stats.avg_execution_ms > 0
    
    def test_reset_stats(self, bulkhead):
        """Stats can be reset."""
        bulkhead._total_completed = 100
        bulkhead._total_failed = 50
        
        bulkhead.reset_stats()
        
        stats = bulkhead.get_stats()
        assert stats.total_completed == 0
        assert stats.total_failed == 0


class TestBulkheadConcurrency:
    """Tests for concurrent bulkhead operations."""
    
    @pytest.fixture
    def bulkhead(self):
        return Bulkhead(name="concurrent", max_concurrent=3, max_queued=10)
    
    @pytest.mark.asyncio
    async def test_concurrent_operations(self, bulkhead):
        """Multiple concurrent operations work correctly."""
        results = []
        
        async def worker(id: int):
            async with bulkhead:
                results.append(f"start_{id}")
                await asyncio.sleep(0.05)
                results.append(f"end_{id}")
        
        # Start 5 workers (only 3 can run concurrently)
        tasks = [asyncio.create_task(worker(i)) for i in range(5)]
        await asyncio.gather(*tasks)
        
        # All should complete
        assert len([r for r in results if r.startswith("end_")]) == 5
    
    @pytest.mark.asyncio
    async def test_fifo_queue_order(self, bulkhead):
        """Queued operations are processed in order."""
        order = []
        
        async def worker(id: int):
            async with bulkhead:
                order.append(id)
                await asyncio.sleep(0.02)
        
        # Fill concurrent slots
        t1 = asyncio.create_task(worker(1))
        t2 = asyncio.create_task(worker(2))
        t3 = asyncio.create_task(worker(3))
        await asyncio.sleep(0.01)  # Let them acquire
        
        # Queue additional workers
        t4 = asyncio.create_task(worker(4))
        t5 = asyncio.create_task(worker(5))
        
        await asyncio.gather(t1, t2, t3, t4, t5)
        
        # First 3 should be in first batch, 4 and 5 after
        assert 4 in order[3:]
        assert 5 in order[3:]


class TestBulkheadRegistry:
    """Tests for bulkhead registry."""
    
    @pytest.fixture(autouse=True)
    def reset_registry(self):
        """Reset registry between tests."""
        reset_all_bulkheads()
        yield
        reset_all_bulkheads()
    
    def test_get_bulkhead_creates_new(self):
        """get_bulkhead creates new bulkhead if not exists."""
        b = get_bulkhead("new_venue", max_concurrent=5)
        
        assert b.name == "new_venue"
        assert b.max_concurrent == 5
    
    def test_get_bulkhead_returns_existing(self):
        """get_bulkhead returns existing bulkhead."""
        b1 = get_bulkhead("venue_a", max_concurrent=5)
        b2 = get_bulkhead("venue_a")
        
        assert b1 is b2
    
    def test_get_all_bulkheads(self):
        """get_all_bulkheads returns all registered bulkheads."""
        get_bulkhead("kalshi")
        get_bulkhead("polymarket")
        
        all_bulkheads = get_all_bulkheads()
        
        assert "kalshi" in all_bulkheads
        assert "polymarket" in all_bulkheads
    
    def test_reset_all_bulkheads(self):
        """reset_all_bulkheads resets stats for all."""
        b = get_bulkhead("test_reset")
        b._total_completed = 100
        
        reset_all_bulkheads()
        
        assert b._total_completed == 0


class TestBulkheadStats:
    """Tests for BulkheadStats dataclass."""
    
    def test_stats_dataclass(self):
        """BulkheadStats holds correct data."""
        stats = BulkheadStats(
            name="test",
            max_concurrent=10,
            max_queued=50,
            active_count=3,
            queued_count=5,
            total_accepted=100,
            total_rejected=2,
            total_completed=95,
            total_failed=3,
            avg_wait_ms=15.5,
            avg_execution_ms=250.0,
        )
        
        assert stats.name == "test"
        assert stats.max_concurrent == 10
        assert stats.total_accepted == 100
        assert stats.avg_execution_ms == 250.0
