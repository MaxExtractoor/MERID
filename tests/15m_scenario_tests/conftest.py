"""
Pytest fixtures for 15m scenario tests.

All fixtures ensure tests run under MERID_RUNTIME_MODE=15m_live.
"""

import pytest
import os
import time
from unittest.mock import Mock, MagicMock
from typing import Dict, Any


@pytest.fixture(autouse=True)
def set_15m_mode():
    """Ensure all tests run in 15m live mode."""
    original_mode = os.environ.get('MERID_RUNTIME_MODE')
    original_profile = os.environ.get('MERID_PROFILE')
    
    os.environ['MERID_RUNTIME_MODE'] = '15m_live'
    os.environ['MERID_PROFILE'] = 'kalshi_crypto_15m_v2'
    
    yield
    
    # Restore original values
    if original_mode:
        os.environ['MERID_RUNTIME_MODE'] = original_mode
    elif 'MERID_RUNTIME_MODE' in os.environ:
        del os.environ['MERID_RUNTIME_MODE']
    
    if original_profile:
        os.environ['MERID_PROFILE'] = original_profile
    elif 'MERID_PROFILE' in os.environ:
        del os.environ['MERID_PROFILE']


@pytest.fixture
def mock_ws_bridge():
    """Mock WS bridge for scenario testing."""
    bridge = Mock()
    bridge.connection_state = "CONNECTED"
    bridge.latency = 0.1  # 100ms
    bridge.last_heartbeat = time.time()
    bridge.is_connected = True
    return bridge


@pytest.fixture
def mock_spot_service():
    """Mock spot service for scenario testing."""
    spot = Mock()
    spot.last_update_age = 5.0  # 5 seconds old (fresh)
    spot._running = True
    spot._freshness_threshold_s = 30.0
    return spot


@pytest.fixture
def mock_market_state():
    """Mock market state for scenario testing."""
    state = Mock()
    state.book_consistency = "GOOD"
    state.suspect_reason = None
    state.bids = [[99, 10], [98, 20]]  # [price_cents, quantity]
    state.asks = [[101, 10], [102, 20]]
    state.last_update_ts = time.time()
    state.best_bid_cents = 99
    state.best_ask_cents = 101
    state.mid_cents = 100
    state.executable = True
    return state


@pytest.fixture
def mock_agent():
    """Mock agent for scenario testing."""
    agent = Mock()
    agent.signal_generated = False
    agent.asset = "BTC"
    agent.market_id = "BTC-15m-2026-06-05"
    agent.enabled = True
    return agent


@pytest.fixture
def mock_risk_env():
    """Mock risk environment for scenario testing."""
    risk = Mock()
    risk.utilization = Mock(return_value=0.3)  # 30% utilized
    risk.has_capacity = Mock(return_value=True)
    return risk


@pytest.fixture
def gate_decision():
    """Mock gate decision object."""
    from dataclasses import dataclass
    
    @dataclass
    class GateDecision:
        spot_age: str = "PASS"
        book_freshness: str = "PASS"
        liquidity: str = "PASS"
        data_quality: str = "PASS"
        edge: str = "PASS"
        risk: str = "PASS"
        overall: str = "PASS"
        reason: str = ""
    
    return GateDecision()


@pytest.fixture
def evaluate_gates():
    """Helper function to evaluate gate decisions."""
    def _evaluate(
        ws_bridge,
        market_state,
        spot_age,
        risk_env=None,
        edge_threshold=1.0,
        edge_calculated=2.0,
    ) -> Any:
        """Evaluate gate decisions based on scenario conditions."""
        from dataclasses import dataclass
        
        @dataclass
        class GateDecision:
            spot_age: str
            book_freshness: str
            liquidity: str
            data_quality: str
            edge: str
            risk: str
            overall: str
            reason: str
        
        # Spot age gate
        spot_age_gate = "PASS" if spot_age < 60 else "FAIL"
        
        # Book freshness gate (consider book age, WS latency, and book consistency)
        book_age = time.time() - market_state.last_update_ts
        ws_latency = getattr(ws_bridge, 'latency', 0.0)
        # Book fails if: stale (>10s) OR WS has high latency (>5s) OR book is SUSPECT
        book_freshness_gate = "PASS" if (book_age < 10 and ws_latency < 5.0 and market_state.book_consistency == "GOOD") else "FAIL"
        
        # Liquidity gate (consider both presence and book consistency)
        has_bids = len(market_state.bids) > 0
        has_asks = len(market_state.asks) > 0
        is_dual_sided = has_bids and has_asks
        # Liquidity fails if not dual-sided OR book is SUSPECT
        liquidity_gate = "PASS" if (is_dual_sided and market_state.book_consistency == "GOOD") else "FAIL"
        
        # Data quality gate (consider book consistency, one-sided, staleness, and book freshness)
        # Data quality fails if: SUSPECT, one-sided, stale, OR book freshness failed
        is_stale = book_age >= 10
        data_quality_gate = "PASS" if (market_state.book_consistency == "GOOD" and is_dual_sided and not is_stale and book_freshness_gate == "PASS") else "FAIL"
        
        # Edge gate
        edge_gate = "PASS" if edge_calculated >= edge_threshold else "FAIL"
        
        # Risk gate
        if risk_env:
            risk_gate = "PASS" if risk_env.has_capacity() else "FAIL"
        else:
            risk_gate = "PASS"
        
        # Overall gate
        gates = [spot_age_gate, book_freshness_gate, liquidity_gate, data_quality_gate, edge_gate, risk_gate]
        overall_gate = "PASS" if all(g == "PASS" for g in gates) else "REJECT"
        
        # Determine reason (check in priority order)
        reason = ""
        if overall_gate == "REJECT":
            if spot_age_gate == "FAIL":
                reason = "spot_stale"
            elif market_state.book_consistency == "SUSPECT":
                reason = "book_suspect"
            elif book_freshness_gate == "FAIL":
                reason = "book_stale"
            elif liquidity_gate == "FAIL":
                reason = "insufficient_liquidity"
            elif data_quality_gate == "FAIL":
                reason = "book_suspect"
            elif edge_gate == "FAIL":
                reason = "edge_insufficient"
            elif risk_gate == "FAIL":
                reason = "risk_budget_exhausted"
        
        return GateDecision(
            spot_age=spot_age_gate,
            book_freshness=book_freshness_gate,
            liquidity=liquidity_gate,
            data_quality=data_quality_gate,
            edge=edge_gate,
            risk=risk_gate,
            overall=overall_gate,
            reason=reason,
        )
    
    return _evaluate
