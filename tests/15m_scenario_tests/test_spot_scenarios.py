"""
Spot service scenario tests for 15m stack.

Tests gate decisions and system behavior when spot price data
is stale, fresh, or the spot service is restarting.
"""

import time
import pytest


def test_spot_stale_scenario(mock_ws_bridge, mock_market_state, mock_spot_service, evaluate_gates):
    """Test gate decisions when spot data is stale (> 60s).
    
    Expected:
    - Spot Age Gate: FAIL (spot > 60s)
    - Book Freshness Gate: PASS (WS healthy)
    - Liquidity Gate: PASS
    - Data Quality Gate: PASS
    - Overall Gate: REJECT
    """
    # Setup: WS healthy, spot stale
    mock_ws_bridge.connection_state = "CONNECTED"
    mock_ws_bridge.is_connected = True
    mock_market_state.book_consistency = "GOOD"
    mock_market_state.last_update_ts = time.time() - 1  # 1s old (fresh)
    mock_spot_service.last_update_age = 65.0  # 65s old (stale)
    
    # Evaluate gates
    gate_decision = evaluate_gates(
        ws_bridge=mock_ws_bridge,
        market_state=mock_market_state,
        spot_age=mock_spot_service.last_update_age,
    )
    
    # Assertions
    assert gate_decision.spot_age == "FAIL", "Spot age gate should fail when spot > 60s"
    assert gate_decision.book_freshness == "PASS", "Book freshness should pass with healthy WS"
    assert gate_decision.liquidity == "PASS", "Liquidity should pass"
    assert gate_decision.data_quality == "PASS", "Data quality should pass"
    assert gate_decision.overall == "REJECT", "Overall gate should reject with stale spot"
    assert gate_decision.reason == "spot_stale", "Reason should be spot_stale"


def test_spot_fresh_scenario(mock_ws_bridge, mock_market_state, mock_spot_service, evaluate_gates):
    """Test gate decisions when spot data is fresh (< 30s).
    
    Expected:
    - Spot Age Gate: PASS
    - Book Freshness Gate: PASS
    - Liquidity Gate: PASS
    - Data Quality Gate: PASS
    - Overall Gate: PASS (if other gates pass)
    """
    # Setup: WS healthy, spot fresh
    mock_ws_bridge.connection_state = "CONNECTED"
    mock_ws_bridge.is_connected = True
    mock_market_state.book_consistency = "GOOD"
    mock_market_state.last_update_ts = time.time() - 1  # 1s old
    mock_spot_service.last_update_age = 5.0  # 5s old (fresh)
    
    # Evaluate gates
    gate_decision = evaluate_gates(
        ws_bridge=mock_ws_bridge,
        market_state=mock_market_state,
        spot_age=mock_spot_service.last_update_age,
    )
    
    # Assertions
    assert gate_decision.spot_age == "PASS", "Spot age gate should pass when spot < 30s"
    assert gate_decision.book_freshness == "PASS", "Book freshness should pass"
    assert gate_decision.liquidity == "PASS", "Liquidity should pass"
    assert gate_decision.data_quality == "PASS", "Data quality should pass"
    assert gate_decision.overall == "PASS", "Overall gate should pass with fresh spot"


def test_spot_boundary_30s_scenario(mock_ws_bridge, mock_market_state, mock_spot_service, evaluate_gates):
    """Test gate decisions at spot age boundary (30s).
    
    Expected:
    - Spot Age Gate: PASS (30s is still within reasonable threshold)
    - Overall Gate: PASS (if other gates pass)
    """
    # Setup: spot at exactly 30s boundary
    mock_ws_bridge.connection_state = "CONNECTED"
    mock_ws_bridge.is_connected = True
    mock_market_state.book_consistency = "GOOD"
    mock_market_state.last_update_ts = time.time() - 1
    mock_spot_service.last_update_age = 30.0  # 30s old (boundary)
    
    # Evaluate gates
    gate_decision = evaluate_gates(
        ws_bridge=mock_ws_bridge,
        market_state=mock_market_state,
        spot_age=mock_spot_service.last_update_age,
    )
    
    # Assertions
    assert gate_decision.spot_age == "PASS", "Spot age gate should pass at 30s boundary"
    assert gate_decision.overall == "PASS", "Overall gate should pass at 30s boundary"


def test_spot_boundary_60s_scenario(mock_ws_bridge, mock_market_state, mock_spot_service, evaluate_gates):
    """Test gate decisions at spot age hard fail boundary (60s).
    
    Expected:
    - Spot Age Gate: FAIL (60s is hard fail threshold)
    - Overall Gate: REJECT
    """
    # Setup: spot at exactly 60s boundary
    mock_ws_bridge.connection_state = "CONNECTED"
    mock_ws_bridge.is_connected = True
    mock_market_state.book_consistency = "GOOD"
    mock_market_state.last_update_ts = time.time() - 1
    mock_spot_service.last_update_age = 60.0  # 60s old (hard fail boundary)
    
    # Evaluate gates
    gate_decision = evaluate_gates(
        ws_bridge=mock_ws_bridge,
        market_state=mock_market_state,
        spot_age=mock_spot_service.last_update_age,
    )
    
    # Assertions
    assert gate_decision.spot_age == "FAIL", "Spot age gate should fail at 60s boundary"
    assert gate_decision.overall == "REJECT", "Overall gate should reject at 60s boundary"
    assert gate_decision.reason == "spot_stale", "Reason should be spot_stale"


def test_spot_service_restart_scenario(mock_ws_bridge, mock_market_state, mock_spot_service, evaluate_gates):
    """Test gate decisions during spot service restart.
    
    Expected:
    - During restart: spot age gate fails
    - After restart: spot age gate passes
    """
    # Setup: spot service restarting (spot very stale)
    mock_ws_bridge.connection_state = "CONNECTED"
    mock_ws_bridge.is_connected = True
    mock_market_state.book_consistency = "GOOD"
    mock_market_state.last_update_ts = time.time() - 1
    mock_spot_service.last_update_age = 120.0  # 120s old (service restarting)
    mock_spot_service._running = False
    
    # Evaluate gates during restart
    gate_decision_restart = evaluate_gates(
        ws_bridge=mock_ws_bridge,
        market_state=mock_market_state,
        spot_age=mock_spot_service.last_update_age,
    )
    
    # Assertions during restart
    assert gate_decision_restart.spot_age == "FAIL", "Should fail during spot service restart"
    assert gate_decision_restart.overall == "REJECT", "Should reject during spot service restart"
    
    # Setup: spot service restarted
    mock_spot_service.last_update_age = 5.0  # 5s old (fresh)
    mock_spot_service._running = True
    
    # Evaluate gates after restart
    gate_decision_restarted = evaluate_gates(
        ws_bridge=mock_ws_bridge,
        market_state=mock_market_state,
        spot_age=mock_spot_service.last_update_age,
    )
    
    # Assertions after restart
    assert gate_decision_restarted.spot_age == "PASS", "Should pass after spot service restart"
    assert gate_decision_restarted.overall == "PASS", "Should pass after spot service restart"


def test_spot_missing_scenario(mock_ws_bridge, mock_market_state, mock_spot_service, evaluate_gates):
    """Test gate decisions when spot data is completely missing.
    
    Expected:
    - Spot Age Gate: FAIL (no spot data)
    - Overall Gate: REJECT
    """
    # Setup: spot data missing (age = None or very large)
    mock_ws_bridge.connection_state = "CONNECTED"
    mock_ws_bridge.is_connected = True
    mock_market_state.book_consistency = "GOOD"
    mock_market_state.last_update_ts = time.time() - 1
    mock_spot_service.last_update_age = 9999.0  # Effectively missing
    
    # Evaluate gates
    gate_decision = evaluate_gates(
        ws_bridge=mock_ws_bridge,
        market_state=mock_market_state,
        spot_age=mock_spot_service.last_update_age,
    )
    
    # Assertions
    assert gate_decision.spot_age == "FAIL", "Spot age gate should fail when spot missing"
    assert gate_decision.overall == "REJECT", "Overall gate should reject when spot missing"
    assert gate_decision.reason == "spot_stale", "Reason should be spot_stale"
