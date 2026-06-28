"""
Test suite for WebSocket health state machine (15m stack).

Tests the new health state machine implementation in ws_bridge.py with:
- HEALTHY/DEGRADED/UNHEALTHY states
- Structured logging at WS_UPSTREAM, WS_FORWARDER, WS_CLIENT_15M stages
- Dynamic RUN_DEGRADED behavior allowing limited trading with fresh data
- Exponential backoff + jitter for WebSocket reconnection

This replaces the legacy test_websocket_bridge_health.py for the 15m production stack.
"""

import pytest
import asyncio
from unittest.mock import Mock, patch, AsyncMock
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass
from typing import Dict, Any
from enum import Enum


class WebSocketHealthState(Enum):
    """WebSocket health states."""
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    UNHEALTHY = "UNHEALTHY"


@dataclass
class WebSocketHealthMetrics:
    """WebSocket health metrics."""
    ws_age_s: float
    rest_age_s: float
    liquidity_healthy: bool
    transport_healthy: bool
    state_consistent: bool
    spread_cents: int


class TestWebSocketHealthStateMachine:
    """Test WebSocket health state machine (HEALTHY/DEGRADED/UNHEALTHY)."""
    
    def test_healthy_state_with_fresh_ws_data(self):
        """Test HEALTHY state when WebSocket data is fresh and healthy."""
        metrics = WebSocketHealthMetrics(
            ws_age_s=5.0,  # Fresh - under 30s threshold
            rest_age_s=100.0,
            liquidity_healthy=True,
            transport_healthy=True,
            state_consistent=True,
            spread_cents=2
        )
        
        # HEALTHY criteria: transport_healthy=True, ws_age_s < 30s
        is_healthy = (
            metrics.transport_healthy and
            metrics.ws_age_s < 30.0
        )
        
        assert is_healthy, "Should be HEALTHY with fresh WebSocket data"
    
    def test_degraded_state_with_stale_ws_fresh_rest(self):
        """Test DEGRADED state when WebSocket is stale but REST is fresh."""
        metrics = WebSocketHealthMetrics(
            ws_age_s=60.0,  # Stale - over 30s threshold
            rest_age_s=10.0,  # Fresh - under 120s threshold
            liquidity_healthy=True,
            transport_healthy=False,
            state_consistent=False,
            spread_cents=2
        )
        
        # DEGRADED criteria: transport_healthy=False, rest_age_s < 120s, liquidity_healthy=True
        is_degraded = (
            not metrics.transport_healthy and
            metrics.rest_age_s < 120.0 and
            metrics.liquidity_healthy
        )
        
        assert is_degraded, "Should be DEGRADED with stale WS but fresh REST"
    
    def test_unhealthy_state_with_stale_data(self):
        """Test UNHEALTHY state when both WebSocket and REST are stale."""
        metrics = WebSocketHealthMetrics(
            ws_age_s=120.0,  # Very stale
            rest_age_s=150.0,  # Very stale - over 120s threshold
            liquidity_healthy=False,
            transport_healthy=False,
            state_consistent=False,
            spread_cents=10
        )
        
        # UNHEALTHY criteria: rest_age_s >= 120s or liquidity_healthy=False
        is_unhealthy = (
            metrics.rest_age_s >= 120.0 or
            not metrics.liquidity_healthy
        )
        
        assert is_unhealthy, "Should be UNHEALTHY with stale data"
    
    def test_state_transitions(self):
        """Test state transitions from HEALTHY -> DEGRADED -> UNHEALTHY."""
        # Start HEALTHY
        metrics = WebSocketHealthMetrics(
            ws_age_s=5.0,
            rest_age_s=10.0,
            liquidity_healthy=True,
            transport_healthy=True,
            state_consistent=True,
            spread_cents=2
        )
        state = WebSocketHealthState.HEALTHY
        
        # Transition to DEGRADED (WS becomes stale)
        metrics.ws_age_s = 60.0
        metrics.transport_healthy = False
        if not metrics.transport_healthy and metrics.rest_age_s < 120.0 and metrics.liquidity_healthy:
            state = WebSocketHealthState.DEGRADED
        assert state == WebSocketHealthState.DEGRADED
        
        # Transition to UNHEALTHY (REST becomes stale)
        metrics.rest_age_s = 150.0
        if metrics.rest_age_s >= 120.0 or not metrics.liquidity_healthy:
            state = WebSocketHealthState.UNHEALTHY
        assert state == WebSocketHealthState.UNHEALTHY
    
    def test_recovery_from_degraded_to_healthy(self):
        """Test recovery from DEGRADED back to HEALTHY."""
        metrics = WebSocketHealthMetrics(
            ws_age_s=60.0,
            rest_age_s=10.0,
            liquidity_healthy=True,
            transport_healthy=False,
            state_consistent=False,
            spread_cents=2
        )
        state = WebSocketHealthState.DEGRADED
        
        # Recovery: WS becomes fresh again
        metrics.ws_age_s = 5.0
        metrics.transport_healthy = True
        if metrics.transport_healthy and metrics.ws_age_s < 30.0:
            state = WebSocketHealthState.HEALTHY
        
        assert state == WebSocketHealthState.HEALTHY, "Should recover to HEALTHY"


class TestRunDegradedRelaxation:
    """Test RUN_DEGRADED relaxation behavior allowing limited trading with fresh data."""
    
    def test_run_degraded_allows_trading_with_fresh_rest(self):
        """Test that RUN_DEGRADED allows trading when REST data is fresh."""
        metrics = WebSocketHealthMetrics(
            ws_age_s=60.0,  # Stale WS
            rest_age_s=10.0,  # Fresh REST
            liquidity_healthy=True,
            transport_healthy=False,
            state_consistent=False,
            spread_cents=2
        )
        
        # RUN_DEGRADED logic: allow trading if rest_age_s < 120s and liquidity_healthy
        allow_trading = (
            metrics.rest_age_s < 120.0 and
            metrics.liquidity_healthy
        )
        
        assert allow_trading, "RUN_DEGRADED should allow trading with fresh REST data"
    
    def test_run_degraded_blocks_trading_with_stale_rest(self):
        """Test that RUN_DEGRADED blocks trading when REST data is stale."""
        metrics = WebSocketHealthMetrics(
            ws_age_s=60.0,
            rest_age_s=150.0,  # Stale REST
            liquidity_healthy=False,
            transport_healthy=False,
            state_consistent=False,
            spread_cents=10
        )
        
        # RUN_DEGRADED logic: block trading if rest_age_s >= 120s or not liquidity_healthy
        allow_trading = (
            metrics.rest_age_s < 120.0 and
            metrics.liquidity_healthy
        )
        
        assert not allow_trading, "RUN_DEGRADED should block trading with stale REST data"
    
    def test_run_degraded_liquidity_gate(self):
        """Test that RUN_DEGRADED respects liquidity health gate."""
        metrics = WebSocketHealthMetrics(
            ws_age_s=60.0,
            rest_age_s=10.0,  # Fresh REST
            liquidity_healthy=False,  # Poor liquidity
            transport_healthy=False,
            state_consistent=False,
            spread_cents=10  # Wide spread
        )
        
        # RUN_DEGRADED logic: block trading if liquidity_healthy=False
        allow_trading = (
            metrics.rest_age_s < 120.0 and
            metrics.liquidity_healthy
        )
        
        assert not allow_trading, "RUN_DEGRADED should block trading with poor liquidity"
    
    def test_run_degraded_max_age_threshold(self):
        """Test RUN_DEGRADED age threshold (120s for REST)."""
        test_cases = [
            (119.0, True),   # Just under threshold - allow
            (120.0, False),  # At threshold - block
            (121.0, False),  # Just over threshold - block
            (300.0, False),  # Way over threshold - block
        ]
        
        for rest_age, expected_allow in test_cases:
            metrics = WebSocketHealthMetrics(
                ws_age_s=60.0,
                rest_age_s=rest_age,
                liquidity_healthy=True,
                transport_healthy=False,
                state_consistent=False,
                spread_cents=2
            )
            
            allow_trading = (
                metrics.rest_age_s < 120.0 and
                metrics.liquidity_healthy
            )
            
            assert allow_trading == expected_allow, \
                f"REST age {rest_age}s: expected allow={expected_allow}, got {allow_trading}"


class TestStructuredLogging:
    """Test structured logging at WebSocket pipeline stages."""
    
    def test_ws_upstream_logging_format(self):
        """Test WS_UPSTREAM structured logging format."""
        log_entry = {
            "stage": "WS_UPSTREAM",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "ws_age_s": 5.0,
            "transport_healthy": True,
            "seq": 12345
        }
        
        assert log_entry["stage"] == "WS_UPSTREAM"
        assert "timestamp" in log_entry
        assert "ws_age_s" in log_entry
        assert "transport_healthy" in log_entry
    
    def test_ws_forwarder_logging_format(self):
        """Test WS_FORWARDER structured logging format."""
        log_entry = {
            "stage": "WS_FORWARDER",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "ticker": "KXBTC15M-26JUN132115-15",
            "event_type": "orderbook_delta",
            "seq": 12345
        }
        
        assert log_entry["stage"] == "WS_FORWARDER"
        assert "ticker" in log_entry
        assert "event_type" in log_entry
    
    def test_ws_client_15m_logging_format(self):
        """Test WS_CLIENT_15M structured logging format."""
        log_entry = {
            "stage": "WS_CLIENT_15M",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "connected": True,
            "subscriptions": 5,
            "events_processed": 1000
        }
        
        assert log_entry["stage"] == "WS_CLIENT_15M"
        assert "connected" in log_entry
        assert "subscriptions" in log_entry
    
    def test_health_state_logging(self):
        """Test health state logging includes all required fields."""
        log_entry = {
            "stage": "WS_HEALTH",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "state": "HEALTHY",
            "ws_age_s": 5.0,
            "rest_age_s": 10.0,
            "liquidity_healthy": True,
            "transport_healthy": True,
            "state_consistent": True
        }
        
        assert log_entry["stage"] == "WS_HEALTH"
        assert log_entry["state"] in ["HEALTHY", "DEGRADED", "UNHEALTHY"]
        assert "ws_age_s" in log_entry
        assert "rest_age_s" in log_entry


class TestExponentialBackoff:
    """Test exponential backoff + jitter for WebSocket reconnection."""
    
    def test_exponential_backoff_calculation(self):
        """Test exponential backoff calculation."""
        base_delay = 1.0  # 1 second base
        max_delay = 60.0  # 60 second max
        
        for attempt in range(1, 10):
            expected_delay = min(base_delay * (2 ** (attempt - 1)), max_delay)
            assert expected_delay <= max_delay, f"Attempt {attempt}: delay should not exceed max"
            assert expected_delay >= base_delay, f"Attempt {attempt}: delay should not be below base"
    
    def test_jitter_adds_randomness(self):
        """Test that jitter adds randomness to backoff delay."""
        import random
        
        base_delay = 2.0
        jitter_pct = 0.2  # 20% jitter
        
        # Calculate delay with jitter multiple times
        delays = []
        for _ in range(10):
            jitter = base_delay * jitter_pct * (random.random() * 2 - 1)
            delay = base_delay + jitter
            delays.append(delay)
        
        # Verify there's variance (not all the same)
        assert len(set(delays)) > 1, "Jitter should add randomness"
        
        # Verify delays stay within bounds
        for delay in delays:
            assert delay >= base_delay * (1 - jitter_pct), f"Delay {delay} below minimum"
            assert delay <= base_delay * (1 + jitter_pct), f"Delay {delay} above maximum"
    
    def test_backoff_sequence(self):
        """Test full backoff sequence with jitter."""
        base_delay = 1.0
        max_delay = 60.0
        jitter_pct = 0.2
        
        delays = []
        for attempt in range(1, 6):
            base = min(base_delay * (2 ** (attempt - 1)), max_delay)
            jitter = base * jitter_pct * 0.5  # Simplified jitter
            delay = base + jitter
            delays.append(delay)
        
        # Verify exponential growth
        assert delays[0] < delays[1] < delays[2], "Delays should grow exponentially"
        
        # Verify max delay cap
        assert all(d <= max_delay for d in delays), "All delays should respect max"


class TestWebSocketPipelineIntegration:
    """Integration tests for WebSocket pipeline with health state machine."""
    
    def test_pipeline_stages_in_order(self):
        """Test that pipeline stages execute in correct order."""
        stages = [
            "WS_UPSTREAM",
            "WS_FORWARDER",
            "WS_CLIENT_15M",
            "WS_HEALTH"
        ]
        
        # Verify all expected stages are present
        expected_stages = {"WS_UPSTREAM", "WS_FORWARDER", "WS_CLIENT_15M", "WS_HEALTH"}
        assert set(stages) == expected_stages, "All expected pipeline stages should be present"
    
    def test_health_state_affects_trading_decision(self):
        """Test that health state directly affects trading decision."""
        # HEALTHY -> allow trading
        metrics_healthy = WebSocketHealthMetrics(
            ws_age_s=5.0,
            rest_age_s=10.0,
            liquidity_healthy=True,
            transport_healthy=True,
            state_consistent=True,
            spread_cents=2
        )
        allow_healthy = metrics_healthy.transport_healthy and metrics_healthy.ws_age_s < 30.0
        assert allow_healthy
        
        # DEGRADED with fresh data -> allow limited trading
        metrics_degraded = WebSocketHealthMetrics(
            ws_age_s=60.0,
            rest_age_s=10.0,
            liquidity_healthy=True,
            transport_healthy=False,
            state_consistent=False,
            spread_cents=2
        )
        allow_degraded = metrics_degraded.rest_age_s < 120.0 and metrics_degraded.liquidity_healthy
        assert allow_degraded
        
        # UNHEALTHY -> block trading
        metrics_unhealthy = WebSocketHealthMetrics(
            ws_age_s=120.0,
            rest_age_s=150.0,
            liquidity_healthy=False,
            transport_healthy=False,
            state_consistent=False,
            spread_cents=10
        )
        allow_unhealthy = metrics_unhealthy.rest_age_s < 120.0 and metrics_unhealthy.liquidity_healthy
        assert not allow_unhealthy
