"""
Regression tests for blocking I/O fixes (2026-05-12).

Tests verify that:
1. ws.py signal handler no longer has blocking time.sleep
2. portfolio_event_log.py uses asyncio.sleep in async contexts
3. market_state.py has explicit timeout on httpx.Client
4. regime_detection.py wraps requests.post in executor
5. main.py lifespan has cooperative shutdown handler
"""
import pytest
import ast
import inspect


class TestWsSignalHandlerFix:
    """Verify ws.py signal handler no longer blocks with time.sleep."""
    
    def test_signal_handler_no_blocking_sleep(self):
        """Signal handler should not contain blocking time.sleep(0.5) call."""
        from merid.event_venues.kalshi import ws
        
        # Get the register_sigterm_snapshot method
        source = inspect.getsource(ws.KalshiWebSocket.register_sigterm_snapshot)
        
        # Remove comments to check only actual code
        lines = [line for line in source.split('\n') if not line.strip().startswith('#')]
        code_without_comments = '\n'.join(lines)
        
        # Verify time.sleep(0.5) is NOT in the actual code (excluding comments)
        assert "time.sleep(0.5)" not in code_without_comments, \
            "Signal handler still contains blocking time.sleep(0.5) call"
        
        # Verify the bug fix comment is present
        assert "BUG-FIX (2026-05-12)" in source or "Removed blocking time.sleep" in source, \
            "Missing bug fix comment for signal handler"


class TestPortfolioEventLogFix:
    """Verify portfolio_event_log.py uses asyncio.sleep in async contexts."""
    
    def test_get_connection_asyncio_detection(self):
        """_get_connection should detect async context and use asyncio.sleep."""
        from merid.event_venues.kalshi import portfolio_event_log
        
        # Get the _get_connection method
        source = inspect.getsource(portfolio_event_log.PortfolioEventLog._get_connection)
        
        # Verify asyncio.get_running_loop() is present for async detection
        assert "asyncio.get_running_loop()" in source, \
            "Missing asyncio.get_running_loop() for async context detection"
        
        # Verify asyncio.sleep is used
        assert "asyncio.sleep" in source, \
            "Missing asyncio.sleep in retry logic"
        
        # Verify bug fix comment is present
        assert "BUG-FIX (2026-05-12)" in source, \
            "Missing bug fix comment for portfolio_event_log"


class TestMarketStateFix:
    """Verify market_state.py has explicit timeout on httpx.Client."""
    
    def test_get_trusted_quote_sync_timeout(self):
        """get_trusted_quote_sync should have explicit timeout on httpx.Client."""
        from merid.event_venues.kalshi import market_state
        
        # Get the get_trusted_quote_sync method
        source = inspect.getsource(market_state.KalshiMarketStateStore.get_trusted_quote_sync)
        
        # Verify timeout parameter is present in httpx.Client
        assert "timeout=" in source, \
            "Missing timeout parameter in httpx.Client"
        
        # Verify bug fix comment is present
        assert "BUG-FIX (2026-05-12)" in source or "explicit timeout" in source, \
            "Missing bug fix comment for market_state timeout"


class TestRegimeDetectionFix:
    """Verify regime_detection.py wraps requests.post in executor."""
    
    def test_webhook_callback_executor_wrapper(self):
        """create_webhook_alert_callback should wrap requests.post in executor."""
        from merid.event_venues.kalshi import regime_detection
        
        # Get the create_webhook_alert_callback function
        source = inspect.getsource(regime_detection.create_webhook_alert_callback)
        
        # Verify ThreadPoolExecutor is used
        assert "ThreadPoolExecutor" in source, \
            "Missing ThreadPoolExecutor for blocking HTTP call"
        
        # Verify executor.submit is used
        assert "executor.submit" in source or "run_in_executor" in source, \
            "Missing executor submission for blocking HTTP call"
        
        # Verify timeout is present on future.result()
        assert "future.result(timeout=" in source, \
            "Missing timeout on future.result()"
        
        # Verify bug fix comment is present
        assert "BUG-FIX (2026-05-12)" in source, \
            "Missing bug fix comment for regime_detection executor"


class TestMainLifespanShutdownFix:
    """Verify main.py lifespan has cooperative shutdown handler."""
    
    def test_cooperative_task_cancellation(self):
        """Lifespan shutdown should cancel tasks with timeout."""
        from web import main
        
        # Get the _app_lifespan function
        source = inspect.getsource(main._app_lifespan)
        
        # Verify task.cancel() is called
        assert "task.cancel()" in source, \
            "Missing task.cancel() in shutdown sequence"
        
        # Verify asyncio.wait_for is used for timeout
        assert "asyncio.wait_for" in source, \
            "Missing asyncio.wait_for for shutdown timeout"
        
        # Verify return_exceptions=True is used
        assert "return_exceptions=True" in source, \
            "Missing return_exceptions=True in task gathering"
        
        # Verify bug fix comment is present
        assert "BUG-FIX (2026-05-12)" in source or "Cooperative task cancellation" in source, \
            "Missing bug fix comment for cooperative shutdown"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
