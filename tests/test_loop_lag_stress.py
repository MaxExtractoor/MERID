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
            enable_execution=False,
            venue_poll_interval=5.0,
            strategy_interval=5.0,
            heartbeat_interval=30.0,
        )
        
        loop = MeridLoop(config)
        loop._running = True
        loop.metrics.total_ticks = 100  # Past startup cooldown
        
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
        # Create a slow arb_detector that would block for 5s
        mock_detector = MagicMock()
        async def slow_scan():
            await asyncio.sleep(5.0)
            return []
        mock_detector.detect_arbitrage_opportunities = slow_scan
        
        with patch.object(mock_loop, '_arb_detector', return_value=mock_detector):
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
        # Create mock background tasks
        mock_task1 = MagicMock()
        mock_task1.done.return_value = False
        mock_task1.cancel = MagicMock()
        
        mock_task2 = MagicMock()
        mock_task2.done.return_value = True  # Already done
        
        mock_loop._agent_bg_task = mock_task1
        mock_loop._promo_bg_task = mock_task2
        
        with patch('merid.loop.logger') as mock_logger:
            await mock_loop.shutdown(timeout=1.0)
            
            # Should cancel only the non-done task
            mock_task1.cancel.assert_called_once()
            mock_task2.cancel.assert_not_called()
            
            mock_logger.info.assert_any_call("[SHUTDOWN] Initiating graceful shutdown (timeout=1.0s)")


class TestLoopLagIntegration:
    """Integration tests that verify the full system under load."""

    @pytest.mark.asyncio
    async def test_no_deadlock_under_high_lag(self):
        """Verify the loop remains responsive even when lag spikes."""
        from merid.loop import MeridLoop, LoopConfig
        
        config = LoopConfig(
            active_symbols=["TEST"],
            enable_execution=False,
            venue_poll_interval=1.0,
            strategy_interval=1.0,
            heartbeat_interval=5.0,
        )
        
        loop = MeridLoop(config)
        loop._running = True
        loop.metrics.total_ticks = 100
        
        # Simulate high lag
        with patch.object(loop, '_get_event_loop_lag_ms', return_value=1000.0):
            start = time.monotonic()
            # Run a few ticks
            for _ in range(5):
                await loop._tick_body()
            elapsed = time.monotonic() - start
            
            # Should complete quickly due to skips, not hang
            assert elapsed < 5.0
