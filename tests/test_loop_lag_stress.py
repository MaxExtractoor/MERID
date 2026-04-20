"""Stress test for event-loop lag fixes in MeridLoop.

This test reproduces the lag spike conditions that caused the original crash
and verifies the mitigation prevents graceful shutdown triggers.
"""
import asyncio
import time
import pytest
from unittest.mock import MagicMock, patch, AsyncMock


class TestLoopLagStress:
    """Stress test for event-loop lag guards."""

    @pytest.fixture
    def mock_loop(self):
        """Create a MeridLoop with mocked dependencies."""
        from merid.loop import MeridLoop
        from merid.loop import LoopConfig
        
        config = LoopConfig(
            active_symbols=["TEST"],
            active_domains=["prediction"],
            enable_execution=False,
            enable_reconciliation=False,
        )
        
        loop = MeridLoop(config)
        loop._running = True
        loop.metrics.total_ticks = 200  # Past all startup cooldowns (liquidity needs >120)
        
        # Mock lag monitor
        loop._lag_monitor = MagicMock()
        loop._lag_monitor.get_health.return_value = {"current_ms": 0.0}
        
        return loop

    @pytest.mark.asyncio
    async def test_arb_scan_skips_when_lag_high(self, mock_loop):
        """Verify arb_scan skips when lag >500ms."""
        with patch.object(mock_loop, '_get_event_loop_lag_ms', return_value=600.0):
            with patch('merid.loop.logger') as mock_logger:
                summary = {"actions": []}
                await mock_loop._run_arb_scan(time.time(), summary)
                
                assert "arb_scan:skipped_due_to_lag" in summary["actions"]
                mock_logger.warning.assert_called()
                log_msg = str(mock_logger.warning.call_args)
                assert "LAG-SKIP" in log_msg
                assert "arb_scan" in log_msg
                assert "600" in log_msg

    @pytest.mark.asyncio
    async def test_liquidity_skips_when_lag_high(self, mock_loop):
        """Verify liquidity sweep skips when lag >750ms."""
        with patch.object(mock_loop, '_get_event_loop_lag_ms', return_value=800.0):
            with patch('merid.loop.logger') as mock_logger:
                summary = {"actions": []}
                await mock_loop._refresh_liquidity(time.time(), summary)
                
                assert "liquidity_sweep:skipped_due_to_lag" in summary["actions"]
                mock_logger.warning.assert_called()
                log_msg = str(mock_logger.warning.call_args)
                assert "LAG-SKIP" in log_msg
                assert "liquidity_sweep" in log_msg
                assert "800" in log_msg

    @pytest.mark.asyncio
    async def test_notify_skips_when_lag_critical(self, mock_loop):
        """Verify notify skips entirely when lag >1000ms."""
        mock_loop._subscribers = [MagicMock(), MagicMock()]
        
        with patch.object(mock_loop, '_get_event_loop_lag_ms', return_value=1200.0):
            with patch('merid.loop.logger') as mock_logger:
                await mock_loop._notify("test_event", {})
                
                # No subscribers should have been called
                for sub in mock_loop._subscribers:
                    sub.assert_not_called()
                
                mock_logger.warning.assert_called()
                log_msg = str(mock_logger.warning.call_args)
                assert "LAG-SKIP" in log_msg
                assert "notify" in log_msg
                assert "1200" in log_msg

    @pytest.mark.asyncio
    async def test_arb_scan_timeout_prevents_starvation(self, mock_loop):
        """Verify 2s timeout prevents arb_scan from starving the loop."""
        # Create a slow scanner that would block for 5s when scan() is called
        mock_scanner = MagicMock()
        
        def slow_scan(now):
            # This runs in thread pool, so use time.sleep (not asyncio.sleep)
            import time as _time
            _time.sleep(5.0)
            return []
        
        def slow_synthetic_scan(now):
            import time as _time
            _time.sleep(5.0)
            return []
        
        mock_scanner.scan = slow_scan
        mock_scanner.synthetic_scan = slow_synthetic_scan
        mock_scanner.validate_plans = MagicMock()
        
        with patch.object(mock_loop, '_scanner', return_value=mock_scanner):
            with patch.dict('os.environ', {'MERID_ARB_SCAN_TIMEOUT_S': '2.0'}):
                with patch('merid.loop.logger') as mock_logger:
                    summary = {"actions": []}
                    start = time.monotonic()
                    await mock_loop._run_arb_scan(time.time(), summary)
                    elapsed = time.monotonic() - start
                    
                    # Should complete in ~2s due to timeout, not 5s
                    assert elapsed < 3.0
                    assert "arb_scan:timeout" in summary["actions"]
                    mock_logger.warning.assert_called()

    @pytest.mark.asyncio
    async def test_notify_subscriber_timeout(self, mock_loop):
        """Verify 100ms timeout per subscriber prevents cumulative lag."""
        async def slow_subscriber(event_type, data):
            await asyncio.sleep(10.0)  # Would block for 10s
        
        mock_loop._subscribers = [slow_subscriber]
        
        with patch('merid.loop.logger') as mock_logger:
            start = time.monotonic()
            await mock_loop._notify("test_event", {})
            elapsed = time.monotonic() - start
            
            # Should complete in ~100ms due to timeout, not 10s
            assert elapsed < 0.5
            mock_logger.warning.assert_called()
            log_msg = str(mock_logger.warning.call_args)
            assert "timed out" in log_msg.lower()

    @pytest.mark.asyncio
    async def test_shutdown_cancels_background_tasks(self, mock_loop):
        """Verify shutdown() cancels and awaits background tasks."""
        # Create actual asyncio tasks (mocked coroutines)
        async def mock_coro1():
            try:
                await asyncio.sleep(10)  # Long running
            except asyncio.CancelledError:
                pass
        
        async def mock_coro2():
            return None  # Completes immediately
        
        # Create tasks
        task1 = asyncio.create_task(mock_coro1())
        task2 = asyncio.create_task(mock_coro2())
        
        # Wait for task2 to complete
        await asyncio.sleep(0.01)
        
        mock_loop._agent_bg_task = task1
        mock_loop._promo_bg_task = task2
        
        with patch('merid.loop.logger') as mock_logger:
            await mock_loop.shutdown(timeout=0.5)
            
            # task1 should be cancelled (was running)
            assert task1.cancelled() or task1.done()
            
            # task2 was already done
            assert task2.done()
            
            mock_logger.info.assert_any_call("[SHUTDOWN] Initiating graceful shutdown (timeout=0.5s)")


class TestLoopLagIntegration:
    """Integration tests that verify the full system under load."""

    @pytest.mark.asyncio
    async def test_no_deadlock_under_high_lag(self):
        """Verify the loop remains responsive even when lag spikes."""
        from merid.loop import MeridLoop, LoopConfig
        
        config = LoopConfig(
            active_symbols=["TEST"],
            active_domains=["prediction"],
            enable_execution=False,
            enable_reconciliation=False,
        )
        
        loop = MeridLoop(config)
        loop._running = True
        loop.metrics.total_ticks = 200  # Past all startup cooldowns
        
        # Simulate high lag
        with patch.object(loop, '_get_event_loop_lag_ms', return_value=1000.0):
            start = time.monotonic()
            # Run a few ticks
            for _ in range(5):
                await loop._tick_body()
            elapsed = time.monotonic() - start
            
            # Should complete reasonably quickly due to skips (allow up to 30s for 5 ticks with mocked services)
            assert elapsed < 30.0, f"Expected <30s but took {elapsed:.1f}s - loop may be deadlocked"
