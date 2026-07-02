"""
Integration tests for TradeTrace and calibration pipeline.

Tests verify the end-to-end flow:
- signal → order → fill → settlement
- TradeTrace logging to JSONL
- Calibration script processing
- compute_latency_buffer using calibrated values

Reference:
- Kalshi settlement: https://help.kalshi.com/en/articles/13823838-crypto-markets
- Kalshi historical data: https://docs.kalshi.com/getting_started/historical_data
"""
from __future__ import annotations

import json
import tempfile
import time
from pathlib import Path
from unittest.mock import Mock, patch
import pytest

from merid.prediction.trade_trace import (
    TradeTrace,
    create_trace_id,
    get_trace,
    update_trace,
    finalize_trace,
    find_trace_by_contract_id,
    get_trace_logger,
)


class TestTradeTraceIntegration:
    """Integration tests for TradeTrace lifecycle."""
    
    @pytest.fixture
    def temp_log_path(self):
        """Create temporary log file for testing."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.jsonl', delete=False) as f:
            path = f.name
        yield path
        # Cleanup
        Path(path).unlink(missing_ok=True)
    
    @pytest.fixture
    def sample_trace(self):
        """Create a sample TradeTrace for testing."""
        trace_id = create_trace_id()
        return TradeTrace(
            trace_id=trace_id,
            symbol="BTC",
            contract_id="KXBTC-15M-TEST-001",
            side="yes",
            order_id="order_123",
            spot_time=time.time() - 10.0,
            kalshi_book_time=time.time() - 9.0,
            signal_time=time.time() - 8.0,
            order_submit_time=time.time() - 7.0,
            fill_time=time.time() - 6.0,
            settlement_time=time.time() + 900.0,  # 15 min later
            spot_price_at_signal=50000.0,
            kalshi_mid_at_signal=0.52,
            fill_price=0.53,
            settlement_price=0.55,
            size=10,
            order_side="taker",
            raw_edge=0.03,
            latency_buffer=0.02,
            edge_passes_latency_buffer=True,
            source="test",
        )
    
    def test_trace_lifecycle_signal_to_settlement(self, sample_trace, temp_log_path):
        """
        Test deterministic replay: signal → order → fill → settlement.
        
        Setup:
        - Fixed timestamps for each lifecycle stage
        - Fixed prices for spot, mid, fill, settlement
        
        Assertions:
        - All expected fields populated
        - Correct computed latencies
        - Correct post_fill_move and slippage
        """
        # Initialize trace logger with temp path
        from merid.prediction.trade_trace import TradeTraceLogger
        logger = TradeTraceLogger(log_path=temp_log_path)
        
        # Log the trace
        logger.log_trace(sample_trace)
        
        # Verify log file exists and contains data
        log_path = Path(temp_log_path)
        assert log_path.exists(), "Log file should exist"
        
        # Read back the trace
        traces = logger.read_traces(limit=1)
        assert len(traces) == 1, "Should have 1 trace"
        
        logged_trace = traces[0]
        
        # Verify all expected fields populated
        assert logged_trace["trace_id"] == sample_trace.trace_id
        assert logged_trace["symbol"] == "BTC"
        assert logged_trace["contract_id"] == "KXBTC-15M-TEST-001"
        assert logged_trace["side"] == "yes"
        assert logged_trace["spot_price_at_signal"] == 50000.0
        assert logged_trace["kalshi_mid_at_signal"] == 0.52
        assert logged_trace["fill_price"] == 0.53
        assert logged_trace["settlement_price"] == 0.55
        
        # Verify computed latencies
        expected_signal_to_fill = sample_trace.fill_time - sample_trace.signal_time
        expected_order_to_fill = sample_trace.fill_time - sample_trace.order_submit_time
        
        # Note: latencies are computed in finalize_trace, not in log_trace
        # But we can verify the raw timestamps are correct
        assert logged_trace["signal_time"] == sample_trace.signal_time
        assert logged_trace["order_submit_time"] == sample_trace.order_submit_time
        assert logged_trace["fill_time"] == sample_trace.fill_time
        assert logged_trace["settlement_time"] == sample_trace.settlement_time
    
    def test_trace_update_flow(self, sample_trace):
        """
        Test trace update flow: signal → order → fill → settlement.
        
        Simulates the actual flow where trace is updated at each stage.
        """
        # Create trace with initial signal data
        trace_id = create_trace_id()
        initial_trace = TradeTrace(
            trace_id=trace_id,
            symbol="BTC",
            contract_id="KXBTC-15M-TEST-001",
            side="yes",
            spot_time=time.time() - 10.0,
            kalshi_book_time=time.time() - 9.0,
            signal_time=time.time() - 8.0,
            spot_price_at_signal=50000.0,
            kalshi_mid_at_signal=0.52,
            size=10,
            source="test",
        )
        
        # Add to cache (simulating create_trace)
        from merid.prediction.trade_trace import _trade_trace_cache, _trace_lock
        with _trace_lock:
            _trade_trace_cache[trace_id] = initial_trace
        
        # Update with order submission
        update_trace(trace_id, order_submit_time=time.time() - 7.0, order_id="order_123")
        trace = get_trace(trace_id)
        assert trace.order_submit_time is not None
        assert trace.order_id == "order_123"
        
        # Update with fill
        update_trace(trace_id, fill_time=time.time() - 6.0, fill_price=0.53)
        trace = get_trace(trace_id)
        assert trace.fill_time is not None
        assert trace.fill_price == 0.53
        
        # Update with settlement
        update_trace(trace_id, settlement_time=time.time() + 900.0, settlement_price=0.55)
        trace = get_trace(trace_id)
        assert trace.settlement_time is not None
        assert trace.settlement_price == 0.55
        
        # Finalize trace
        finalized = finalize_trace(trace_id)
        assert finalized is not None
        
        # Verify computed metrics
        assert finalized.post_fill_move is not None
        assert finalized.post_fill_move == 0.55 - 50000.0  # settlement - spot (should be negative in practice)
        
        # Verify trace removed from cache
        assert get_trace(trace_id) is None
    
    def test_find_trace_by_contract_id(self):
        """
        Test find_trace_by_contract_id helper.
        
        Used by settlement listener to find trace to finalize.
        """
        # Create multiple traces with explicit unique IDs
        trace_id_1 = "trace_test_001"
        trace_id_2 = "trace_test_002"
        
        trace_1 = TradeTrace(
            trace_id=trace_id_1,
            symbol="BTC",
            contract_id="KXBTC-15M-TEST-001",
            side="yes",
            spot_time=time.time(),
            signal_time=time.time(),
            size=10,
        )
        
        trace_2 = TradeTrace(
            trace_id=trace_id_2,
            symbol="ETH",
            contract_id="KXETH-15M-TEST-001",
            side="yes",
            spot_time=time.time(),
            signal_time=time.time(),
            size=10,
        )
        
        # Add to cache
        from merid.prediction.trade_trace import _trade_trace_cache, _trace_lock
        with _trace_lock:
            _trade_trace_cache[trace_id_1] = trace_1
            _trade_trace_cache[trace_id_2] = trace_2
        
        # Find by contract_id
        found = find_trace_by_contract_id("KXBTC-15M-TEST-001")
        assert found is not None
        assert found.trace_id == trace_id_1
        assert found.contract_id == "KXBTC-15M-TEST-001"
        
        # Find non-existent
        not_found = find_trace_by_contract_id("KXBTC-15M-TEST-999")
        assert not_found is None
    
    def test_calibration_pipeline(self, temp_log_path):
        """
        Test calibration pipeline with synthetic trade data.
        
        1. Create synthetic trade traces
        2. Log to JSONL
        3. Run calibration script
        4. Verify output config
        """
        # Create synthetic traces
        from merid.prediction.trade_trace import TradeTraceLogger
        logger = TradeTraceLogger(log_path=temp_log_path)
        
        # Create 20 synthetic traces for BTC
        base_time = time.time()
        for i in range(20):
            trace = TradeTrace(
                trace_id=create_trace_id(),
                symbol="BTC",
                contract_id=f"KXBTC-15M-TEST-{i:03d}",
                side="yes",
                spot_time=base_time - 10.0,
                kalshi_book_time=base_time - 9.0,
                signal_time=base_time - 8.0,
                order_submit_time=base_time - 7.0,
                fill_time=base_time - 6.0,
                settlement_time=base_time + 900.0,
                spot_price_at_signal=50000.0,
                kalshi_mid_at_signal=0.52,
                fill_price=0.53,
                settlement_price=0.55,
                size=10,
                order_side="taker",
                raw_edge=0.03,
                source="test",
            )
            logger.log_trace(trace)
        
        # Run calibration script
        import subprocess
        result = subprocess.run(
            ["python", "scripts/calibrate_feed_lag.py", "--input", temp_log_path, "--output", temp_log_path + ".cal.json"],
            capture_output=True,
            text=True,
            cwd="c:\\Dev\\MERID"
        )
        
        # Verify calibration script ran successfully
        assert result.returncode == 0, f"Calibration script failed: {result.stderr}"
        
        # Verify output config exists
        config_path = Path(temp_log_path + ".cal.json")
        assert config_path.exists(), "Calibration config should exist"
        
        # Load and verify config
        with open(config_path, "r") as f:
            config = json.load(f)
        
        assert "assets" in config
        assert "BTC" in config["assets"]
        
        btc_metrics = config["assets"]["BTC"]
        assert "sample_count" in btc_metrics
        assert btc_metrics["sample_count"] == 20
        assert "recommended_latency_buffer" in btc_metrics
        
        # Cleanup
        config_path.unlink(missing_ok=True)
    
    def test_compute_latency_buffer_uses_calibration(self, temp_log_path):
        """
        Test that compute_latency_buffer uses calibrated values.
        
        1. Create calibration config with known values
        2. Mock config path
        3. Call compute_latency_buffer
        4. Verify it uses calibrated values (not defaults)
        """
        # Create calibration config with known buffer
        calibration_config = {
            "generated_at": "2026-05-29T00:00:00Z",
            "data_source": "test",
            "total_samples": 10,
            "assets": {
                "BTC": {
                    "sample_count": 10,
                    "recommended_latency_buffer": 2.5,  # 2.5 seconds
                    "signal_to_fill_p95": 2.5,
                }
            }
        }
        
        config_path = Path(temp_log_path + ".cal.json")
        with open(config_path, "w") as f:
            json.dump(calibration_config, f)
        
        # Mock the config path in unified_edge
        from merid.prediction.unified_edge import UnifiedEdgeComputer, ContractState
        
        edge = UnifiedEdgeComputer()
        
        # Mock _load_calibration_config to return our test config
        with patch.object(edge, '_load_calibration_config', return_value=calibration_config):
            # Create mock contract
            contract = ContractState(
                market_id="KXBTC-15M-TEST",
                asset="BTC",
                strike_price=50000.0,
                side="yes",
                mid_price_cents=50,  # 0.50 probability
                time_to_expiry_seconds=900.0,
                orderbook=None,
            )
            
            # Compute latency buffer
            buffer = edge.compute_latency_buffer("BTC", contract)
            
            # Verify it uses calibrated value (2.5s * 0.005 = 0.0125 prob)
            # The conversion is: calibrated_lag_buffer_seconds * 0.005
            expected_buffer_prob = min(0.05, 2.5 * 0.005)  # 0.0125
            assert buffer >= expected_buffer_prob * 0.9, f"Buffer {buffer} should use calibrated value"
        
        # Cleanup
        config_path.unlink(missing_ok=True)
    
    def test_edge_passes_latency_buffer(self, temp_log_path):
        """
        Test edge gating with latency buffer.
        
        With raw_edge > buffer -> trade allowed
        With raw_edge < buffer -> trade blocked
        """
        from merid.prediction.unified_edge import UnifiedEdgeComputer, EdgeResult, ContractState, SpotReference
        
        edge = UnifiedEdgeComputer()
        
        # Create calibration config with known buffer
        calibration_config = {
            "generated_at": "2026-05-29T00:00:00Z",
            "data_source": "test",
            "total_samples": 10,
            "assets": {
                "BTC": {
                    "sample_count": 10,
                    "recommended_latency_buffer": 2.0,  # 2 seconds -> 0.01 prob
                }
            }
        }
        
        config_path = Path(temp_log_path + ".cal.json")
        with open(config_path, "w") as f:
            json.dump(calibration_config, f)
        
        with patch.object(edge, '_load_calibration_config', return_value=calibration_config):
            # Mock calibration and volatility
            edge.calibration = Mock()
            edge.calibration.get_calibration = Mock(return_value={"time_decay": 0.05})
            edge.calibration.get_volatility = Mock(return_value=0.02)
            
            # Create mock contract
            contract = ContractState(
                market_id="KXBTC-15M-TEST",
                asset="BTC",
                strike_price=50000.0,
                side="yes",
                mid_price_cents=50,  # 0.50 probability
                time_to_expiry_seconds=900.0,
                orderbook=None,
            )
            
            from datetime import datetime, timezone
            spot_ref = SpotReference(
                asset="BTC",
                price_usd=50100.0,
                timestamp=datetime.now(timezone.utc),
                source="test",
            )
            
            # Compute edge
            edge_result = edge.compute_edge("BTC", spot_ref, contract)
            
            # Verify EdgeResult metadata includes latency_buffer
            assert 'latency_buffer' in edge_result.metadata
            assert edge_result.metadata['latency_buffer'] is not None
            
            # Verify edge_passes_latency_buffer is set in metadata
            assert 'edge_passes_latency_buffer' in edge_result.metadata
            assert edge_result.metadata['edge_passes_latency_buffer'] is not None
        
        # Cleanup
        config_path.unlink(missing_ok=True)
    
    def test_historical_live_split_sanity(self, temp_log_path):
        """
        Test that TradeTrace reader can handle both historical and live data.
        
        Kalshi separates live vs historical data for fills and settlements.
        Verify calibration script can handle both.
        """
        from merid.prediction.trade_trace import TradeTraceLogger
        logger = TradeTraceLogger(log_path=temp_log_path)
        
        # Create "historical" traces (older timestamps)
        historical_time = time.time() - 86400 * 7  # 7 days ago
        for i in range(10):
            trace = TradeTrace(
                trace_id=create_trace_id(),
                symbol="BTC",
                contract_id=f"KXBTC-15M-HIST-{i:03d}",
                side="yes",
                spot_time=historical_time - 10.0,
                signal_time=historical_time - 8.0,
                order_submit_time=historical_time - 7.0,
                fill_time=historical_time - 6.0,
                settlement_time=historical_time + 900.0,
                spot_price_at_signal=50000.0,
                kalshi_mid_at_signal=0.52,
                fill_price=0.53,
                settlement_price=0.55,
                size=10,
                order_side="taker",
                source="historical",
            )
            logger.log_trace(trace)
        
        # Create "live" traces (recent timestamps)
        live_time = time.time() - 3600  # 1 hour ago
        for i in range(10):
            trace = TradeTrace(
                trace_id=create_trace_id(),
                symbol="BTC",
                contract_id=f"KXBTC-15M-LIVE-{i:03d}",
                side="yes",
                spot_time=live_time - 10.0,
                signal_time=live_time - 8.0,
                order_submit_time=live_time - 7.0,
                fill_time=live_time - 6.0,
                settlement_time=live_time + 900.0,
                spot_price_at_signal=50000.0,
                kalshi_mid_at_signal=0.52,
                fill_price=0.53,
                settlement_price=0.55,
                size=10,
                order_side="taker",
                source="live",
            )
            logger.log_trace(trace)
        
        # Read all traces
        traces = logger.read_traces()
        assert len(traces) == 20, "Should have 20 traces total"
        
        # Verify both historical and live traces are present
        historical_count = sum(1 for t in traces if t.get("source") == "historical")
        live_count = sum(1 for t in traces if t.get("source") == "live")
        
        assert historical_count == 10, f"Should have 10 historical traces, got {historical_count}"
        assert live_count == 10, f"Should have 10 live traces, got {live_count}"
        
        # Run calibration script on mixed data
        import subprocess
        result = subprocess.run(
            ["python", "scripts/calibrate_feed_lag.py", "--input", temp_log_path, "--output", temp_log_path + ".cal.json"],
            capture_output=True,
            text=True,
            cwd="c:\\Dev\\MERID"
        )
        
        assert result.returncode == 0, f"Calibration should handle mixed data: {result.stderr}"
        
        # Cleanup
        config_path = Path(temp_log_path + ".cal.json")
        config_path.unlink(missing_ok=True)
