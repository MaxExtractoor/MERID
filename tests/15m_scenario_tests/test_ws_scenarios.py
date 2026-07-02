"""
WebSocket scenario tests for 15m stack.

Tests gate decisions and system behavior when WebSocket connection
is down, high latency, or otherwise degraded.
"""

import time
import pytest


def test_ws_down_scenario(mock_ws_bridge, mock_market_state, mock_spot_service, evaluate_gates):
    """Test gate decisions when WebSocket is down.
    
    Expected:
    - Spot Age Gate: PASS (spot independent of WS)
    - Book Freshness Gate: FAIL (book stale)
    - Liquidity Gate: FAIL (no book data)
    - Data Quality Gate: FAIL (SUSPECT state)
    - Overall Gate: REJECT
    """
    # Setup: WS disconnected, book stale
    mock_ws_bridge.connection_state = "DISCONNECTED"
    mock_ws_bridge.is_connected = False
    mock_market_state.book_consistency = "SUSPECT"
    mock_market_state.last_update_ts = time.time() - 100  # 100s old
    mock_spot_service.last_update_age = 5.0  # spot fresh
    
    # Evaluate gates
    gate_decision = evaluate_gates(
        ws_bridge=mock_ws_bridge,
        market_state=mock_market_state,
        spot_age=mock_spot_service.last_update_age,
    )
    
    # Assertions
    assert gate_decision.spot_age == "PASS", "Spot should be fresh even with WS down"
    assert gate_decision.book_freshness == "FAIL", "Book should be stale when WS down"
    assert gate_decision.liquidity == "FAIL", "Liquidity should fail with SUSPECT book"
    assert gate_decision.data_quality == "FAIL", "Data quality should fail with SUSPECT book"
    assert gate_decision.overall == "REJECT", "Overall gate should reject when WS down"
    assert gate_decision.reason == "book_suspect", "Reason should be book_suspect (book is SUSPECT state)"


def test_ws_high_latency_scenario(mock_ws_bridge, mock_market_state, mock_spot_service, evaluate_gates):
    """Test gate decisions when WebSocket has high latency.
    
    Expected:
    - Spot Age Gate: PASS (spot fresh)
    - Book Freshness Gate: FAIL (book stale due to latency)
    - Liquidity Gate: PASS (if book has data)
    - Data Quality Gate: WARN (latency high)
    - Overall Gate: REJECT
    """
    # Setup: WS connected but high latency
    mock_ws_bridge.connection_state = "CONNECTED"
    mock_ws_bridge.is_connected = True
    mock_ws_bridge.latency = 5.5  # 5.5 seconds (above 5s threshold)
    mock_market_state.book_consistency = "GOOD"
    mock_market_state.last_update_ts = time.time() - 8  # 8s old due to latency
    mock_spot_service.last_update_age = 5.0  # spot fresh
    
    # Evaluate gates
    gate_decision = evaluate_gates(
        ws_bridge=mock_ws_bridge,
        market_state=mock_market_state,
        spot_age=mock_spot_service.last_update_age,
    )
    
    # Assertions
    assert gate_decision.spot_age == "PASS", "Spot should be fresh"
    assert gate_decision.book_freshness == "FAIL", "Book should be stale due to high latency"
    assert gate_decision.liquidity == "PASS", "Liquidity should pass if book has data"
    assert gate_decision.data_quality == "FAIL", "Data quality should fail with stale book"
    assert gate_decision.overall == "REJECT", "Overall gate should reject with high latency"
    assert gate_decision.reason == "book_stale", "Reason should be book_stale"


def test_ws_healthy_scenario(mock_ws_bridge, mock_market_state, mock_spot_service, evaluate_gates):
    """Test gate decisions when WebSocket is healthy.
    
    Expected:
    - Spot Age Gate: PASS
    - Book Freshness Gate: PASS
    - Liquidity Gate: PASS
    - Data Quality Gate: PASS
    - Overall Gate: PASS (if other gates pass)
    """
    # Setup: WS healthy
    mock_ws_bridge.connection_state = "CONNECTED"
    mock_ws_bridge.is_connected = True
    mock_ws_bridge.latency = 0.1  # 100ms (healthy)
    mock_market_state.book_consistency = "GOOD"
    mock_market_state.last_update_ts = time.time() - 1  # 1s old (fresh)
    mock_spot_service.last_update_age = 5.0  # spot fresh
    
    # Evaluate gates
    gate_decision = evaluate_gates(
        ws_bridge=mock_ws_bridge,
        market_state=mock_market_state,
        spot_age=mock_spot_service.last_update_age,
    )
    
    # Assertions
    assert gate_decision.spot_age == "PASS", "Spot should be fresh"
    assert gate_decision.book_freshness == "PASS", "Book should be fresh with healthy WS"
    assert gate_decision.liquidity == "PASS", "Liquidity should pass"
    assert gate_decision.data_quality == "PASS", "Data quality should pass with GOOD book"
    assert gate_decision.overall == "PASS", "Overall gate should pass with healthy WS"


def test_ws_reconnect_scenario(mock_ws_bridge, mock_market_state, mock_spot_service, evaluate_gates):
    """Test gate decisions during WS reconnection.
    
    Expected:
    - During reconnection: gates should reject
    - After reconnection: gates should pass
    """
    # Setup: WS reconnecting
    mock_ws_bridge.connection_state = "RECONNECTING"
    mock_ws_bridge.is_connected = False
    mock_market_state.book_consistency = "SUSPECT"
    mock_market_state.last_update_ts = time.time() - 50  # 50s old
    mock_spot_service.last_update_age = 5.0  # spot fresh
    
    # Evaluate gates during reconnection
    gate_decision_reconnecting = evaluate_gates(
        ws_bridge=mock_ws_bridge,
        market_state=mock_market_state,
        spot_age=mock_spot_service.last_update_age,
    )
    
    # Assertions during reconnection
    assert gate_decision_reconnecting.overall == "REJECT", "Should reject during reconnection"
    
    # Setup: WS reconnected
    mock_ws_bridge.connection_state = "CONNECTED"
    mock_ws_bridge.is_connected = True
    mock_market_state.book_consistency = "GOOD"
    mock_market_state.last_update_ts = time.time() - 1  # 1s old
    
    # Evaluate gates after reconnection
    gate_decision_reconnected = evaluate_gates(
        ws_bridge=mock_ws_bridge,
        market_state=mock_market_state,
        spot_age=mock_spot_service.last_update_age,
    )
    
    # Assertions after reconnection
    assert gate_decision_reconnected.overall == "PASS", "Should pass after reconnection"
