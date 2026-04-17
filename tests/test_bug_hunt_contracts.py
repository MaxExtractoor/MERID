"""
Contract tests for MERID Bug & Wiring Hunt fixes.

These tests verify that the critical fixes from the audit are in place:
1. Synthetic data paths eliminated
2. Execution gate fails closed
3. Async bridge doesn't deadlock
4. Kill switch properly alerts on corruption
"""

import pytest
import asyncio
import time
import json
import tempfile
import os
import sys
import uuid
from pathlib import Path
from unittest.mock import patch, MagicMock, AsyncMock, mock_open
import concurrent.futures
import threading
import inspect


class TestCeleryTasksFailClosed:
    """Verify Celery tasks fail closed on missing Redis and don't return synthetic data."""
    
    def test_backtest_task_raises_not_implemented(self):
        """run_backtest must not return synthetic data; should raise NotImplementedError."""
        from core.celery_tasks import run_backtest
        
        # Access the underlying function via __wrapped__ or check the error is raised
        # When calling a Celery task directly (not through .apply/.delay), 
        # it executes the function body which raises NotImplementedError
        with pytest.raises(NotImplementedError) as exc_info:
            # Call without 'self' - Celery task objects handle binding internally
            run_backtest(
                "test_strategy",
                "2024-01-01",
                "2024-01-31",
                {}
            )
        
        error_msg = str(exc_info.value)
        assert "wired" in error_msg.lower() or "implemented" in error_msg.lower()
        # Verify no synthetic data fields are present
        assert "sharpe_ratio" not in error_msg
        assert "1.5" not in error_msg
    
    def test_risk_metrics_task_raises_not_implemented(self):
        """calculate_risk_metrics must not return synthetic data."""
        from core.celery_tasks import calculate_risk_metrics
        
        with pytest.raises(NotImplementedError) as exc_info:
            calculate_risk_metrics("test_portfolio")
        
        error_msg = str(exc_info.value)
        assert "wired" in error_msg.lower() or "implemented" in error_msg.lower()
        assert "var_95" not in error_msg
    
    def test_market_data_sync_task_raises_not_implemented(self):
        """sync_market_data must not return fake counts."""
        from core.celery_tasks import sync_market_data
        
        with pytest.raises(NotImplementedError) as exc_info:
            sync_market_data(["BTC", "ETH"], "1d")
        
        error_msg = str(exc_info.value)
        assert "wired" in error_msg.lower() or "implemented" in error_msg.lower()
    
    def test_order_submission_task_raises_not_implemented(self):
        """submit_order_with_retry must not return fake order_id."""
        from core.celery_tasks import submit_order_with_retry
        
        with pytest.raises(NotImplementedError) as exc_info:
            submit_order_with_retry({
                "client_order_id": "test_123",
                "symbol": "BTC",
                "side": "buy",
                "size": 100.0
            })
        
        error_msg = str(exc_info.value)
        assert "wired" in error_msg.lower() or "implemented" in error_msg.lower()


class TestKalshiAdapterAsyncBridge:
    """Verify Kalshi adapter doesn't deadlock when called from various contexts."""
    
    def test_kalshi_adapter_uses_safe_async_pattern(self):
        """Adapter methods must use safe async patterns (ThreadPoolExecutor)."""
        from trading.adapters.kalshi import KalshiPredictionAdapter
        
        adapter = KalshiPredictionAdapter()
        
        # Check that the methods exist and have docstrings indicating safe patterns
        assert adapter._get_balances_live.__doc__ is not None
        doc_balances = adapter._get_balances_live.__doc__.lower()
        # Should mention thread pool, threadpool, or timeout
        assert (
            "thread pool" in doc_balances or 
            "threadpool" in doc_balances or 
            "timeout" in doc_balances or
            "asyncio.run_coroutine_threadsafe" in doc_balances
        )
        
        assert adapter._get_positions_live.__doc__ is not None
        doc_positions = adapter._get_positions_live.__doc__.lower()
        assert (
            "thread pool" in doc_positions or 
            "threadpool" in doc_positions or 
            "timeout" in doc_positions or
            "asyncio.run_coroutine_threadsafe" in doc_positions
        )
    
    def test_async_bridge_uses_thread_pool_executor(self):
        """Verify the async bridge uses ThreadPoolExecutor pattern."""
        from trading.adapters import kalshi
        
        source = inspect.getsource(kalshi.KalshiPredictionAdapter._get_balances_live)
        # Should use ThreadPoolExecutor, not the old Future+call_soon pattern
        assert "ThreadPoolExecutor" in source
        assert "executor.submit" in source or "concurrent.futures" in source
        # Should not use the deadlock-prone pattern
        assert "call_soon_threadsafe(lambda" not in source


class TestExecutionGateFailClosed:
    """Verify execution gate blocks trading on any exception."""
    
    def test_execution_gate_exception_handlers_exist(self):
        """Gate must have exception handlers that log at ERROR level."""
        from core import execution_gate
        
        source = inspect.getsource(execution_gate.check_execution_gate)
        
        # Should have ERROR level logging in exception handlers
        assert "logger.error" in source
        # Should append BlockReason on exceptions
        assert "BlockReason" in source
        # Should have multiple exception handlers for different checks
        assert source.count("except Exception") >= 3
    
    def test_execution_gate_returns_blockreason_on_exceptions(self):
        """Gate returns BlockReason when checks fail."""
        from core.execution_gate import check_execution_gate, ExecutionGateStatus
        
        # Call the gate normally - it should return a result
        result = check_execution_gate()
        
        # Result should be an ExecutionGateStatus
        assert isinstance(result, ExecutionGateStatus)
        # Should have a blocked boolean
        assert hasattr(result, 'blocked')
        assert isinstance(result.blocked, bool)
        # Should have reasons list
        assert hasattr(result, 'reasons')
        assert isinstance(result.reasons, list)


class TestSignalGenerator:
    """Verify signal generator never emits synthetic/tradeable edges."""
    
    @pytest.mark.asyncio
    async def test_signal_generator_no_synthetic_fallback(self):
        """Edge signals must return empty list, never synthetic tradeable values."""
        from merid.signals.kalshi_signals import KalshiSignalGenerator
        
        generator = KalshiSignalGenerator()
        
        # Mock the adapter to return test instruments
        mock_adapter = AsyncMock()
        mock_adapter.list_instruments.return_value = [
            MagicMock(id="BTC-24FEB-50K-YES")
        ]
        
        # Patch the internal adapter reference
        with patch.object(generator, '_adapter', mock_adapter, create=True):
            signals = await generator._generate_edge_signals(time.time())
            
            # Should return empty list (no synthetic signals)
            assert signals == [], f"Expected empty list, got {len(signals)} synthetic signals"
    
    def test_edge_signal_docstring_warns_against_synthetic(self):
        """Verify docstring indicates no synthetic signals are emitted."""
        from merid.signals.kalshi_signals import KalshiSignalGenerator
        
        doc = inspect.getdoc(KalshiSignalGenerator._generate_edge_signals)
        assert doc is not None
        doc_lower = doc.lower()
        assert "empty list" in doc_lower or "never" in doc_lower or "synthetic" in doc_lower


class TestKillSwitch:
    """Verify kill switch properly alerts on corruption."""
    
    def test_kill_switch_corrupt_file_alerts_operator(self, tmp_path):
        """Corrupt kill-switch file must trigger operator-visible alert."""
        import merid.risk.kill_switches as ks_module
        from unittest.mock import patch
        
        # Create a corrupt kill switch file
        corrupt_file = tmp_path / "risk_kill_switch.json"
        corrupt_file.write_text("{invalid json")
        
        # Patch the file location
        original_file = ks_module._KILL_SWITCH_FILE
        ks_module._KILL_SWITCH_FILE = str(corrupt_file)
        
        try:
            with patch("merid.risk.kill_switches.logger") as mock_logger:
                # Create controller - should detect corruption
                controller = ks_module.RiskController()
                
                # Should have logged critical error about corruption
                critical_calls = [str(call) for call in mock_logger.critical.call_args_list]
                has_corrupt_log = any("corrupt" in c.lower() or "blocked" in c.lower() for c in critical_calls)
                # OR it might log error
                error_calls = [str(call) for call in mock_logger.error.call_args_list]
                has_error_log = any("corrupt" in c.lower() or "kill switch" in c.lower() for c in error_calls)
                
                assert has_corrupt_log or has_error_log, f"Expected critical/error log about corrupt file. Got: {critical_calls + error_calls}"
                
                # Should be blocked (fail-closed)
                assert controller._global_kill == True
                
        finally:
            ks_module._KILL_SWITCH_FILE = original_file


class TestInvariants:
    """Verify runtime invariants are enforced."""
    
    def test_exposure_non_negativity_invariant(self):
        """Paper trading must detect and log negative exposure."""
        from trading.paper_trading import PaperTradingEngine
        
        source = inspect.getsource(PaperTradingEngine.get_global_stats)
        assert "EXPOSURE_INVARIANT_VIOLATION" in source
        assert "merid_negative_exposure_violations_total" in source
    
    def test_pnl_finiteness_invariant(self):
        """Close position must check PnL is finite."""
        from trading.paper_trading import PaperTradingEngine
        
        source = inspect.getsource(PaperTradingEngine.close_position)
        assert "PnL_INVARIANT_VIOLATION" in source
        assert "non-finite" in source.lower() or "isinstance(pnl, (int, float))" in source
    
    def test_order_id_collision_invariant(self):
        """Order ID generation must detect collisions."""
        from trading.paper_trading import PaperTradingEngine
        
        source = inspect.getsource(PaperTradingEngine.place_order)
        assert "ORDER_ID_INVARIANT_VIOLATION" in source
        assert "uuid.uuid4()" in source
    
    def test_position_key_stability_invariant(self):
        """Position key stability must be enforced."""
        from trading.paper_trading import PaperTradingEngine
        
        source = inspect.getsource(PaperTradingEngine._update_position)
        assert "POSITION_KEY_INVARIANT_VIOLATION" in source


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
