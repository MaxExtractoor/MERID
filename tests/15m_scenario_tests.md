# 15m Stack Scenario Tests

**Purpose:** Validate gate decisions and system behavior under critical scenarios for the 15m Kalshi crypto stack.

**Contract:** These tests validate the behavior defined in `docs/kalshi_15m_stack.md` for the canonical 15m stack.

**Runtime Mode:** All tests run under `MERID_RUNTIME_MODE=15m_live`.

---

## Test Suite Structure

```
tests/
├── 15m_scenario_tests/
│   ├── __init__.py
│   ├── conftest.py                 # Pytest fixtures for 15m stack
│   ├── test_ws_scenarios.py        # WebSocket-related scenarios
│   ├── test_spot_scenarios.py      # Spot service scenarios
│   ├── test_book_scenarios.py      # Orderbook scenarios
│   └── test_gate_decisions.py      # Gate decision validation
```

---

## Scenario Definitions

### Scenario 1: WebSocket Down

**Description:** WebSocket connection fails or is disconnected during operation.

**Setup:**
- Simulate WS connection failure (no heartbeat response)
- Market state exists but is aging (no new deltas)
- REST fallback is available

**Expected Gate Decisions:**
- **Spot Age Gate:** PASS (spot service independent of WS)
- **Book Freshness Gate:** FAIL (book stale beyond threshold)
- **Liquidity Gate:** FAIL (no book data)
- **Data Quality Gate:** FAIL (SUSPECT state)
- **Overall Gate:** REJECT (no signal generation)

**Expected System Behavior:**
- WS bridge enters reconnect loop with exponential backoff
- Market state marked as SUSPECT
- REST fallback triggered if enabled
- No orders placed
- Agent grid logs "[GATE-REJECT] book stale - WS down"

**Test Assertions:**
```python
assert agent.signal_generated == False
assert market_state.book_consistency == "SUSPECT"
assert ws_bridge.connection_state == "DISCONNECTED"
assert gate_decision.overall == "REJECT"
assert gate_decision.reason == "book_stale"
```

---

### Scenario 2: Spot Stale

**Description:** Spot price data is stale (older than threshold).

**Setup:**
- WS connection healthy (book fresh)
- Spot service last update > 60 seconds ago
- Watchdog thread would trigger restart

**Expected Gate Decisions:**
- **Spot Age Gate:** FAIL (spot age > 60s hard fail threshold)
- **Book Freshness Gate:** PASS (WS healthy)
- **Liquidity Gate:** PASS (book has liquidity)
- **Data Quality Gate:** PASS (book GOOD)
- **Overall Gate:** REJECT (spot too stale for safe pricing)

**Expected System Behavior:**
- Spot service watchdog logs "[SPOT-STALE] age > 60s, triggering restart"
- No signals generated until spot refreshes
- Agent grid logs "[GATE-REJECT] spot_stale: age=65s"
- If spot service restarts successfully, gates resume PASS

**Test Assertions:**
```python
assert agent.signal_generated == False
assert spot_service.last_update_age > 60
assert gate_decision.spot_age == "FAIL"
assert gate_decision.overall == "REJECT"
assert gate_decision.reason == "spot_stale"
```

---

### Scenario 3: Dual-Sided Book with Good Edge

**Description:** Healthy market with good liquidity and favorable edge.

**Setup:**
- WS connection healthy
- Spot fresh (< 30s)
- Book has both bids and asks (dual-sided)
- Edge calculation shows positive edge (> threshold)
- Liquidity sufficient for desired position size

**Expected Gate Decisions:**
- **Spot Age Gate:** PASS (spot < 30s)
- **Book Freshness Gate:** PASS (book < 10s old)
- **Liquidity Gate:** PASS (sufficient depth)
- **Data Quality Gate:** PASS (book GOOD)
- **Edge Gate:** PASS (edge > threshold)
- **Overall Gate:** PASS (signal generation allowed)

**Expected System Behavior:**
- Agent generates signal
- Order router places order
- Position opened
- Risk budget updated
- Agent grid logs "[GATE-PASS] all gates satisfied, signal generated"

**Test Assertions:**
```python
assert agent.signal_generated == True
assert market_state.book_consistency == "GOOD"
assert gate_decision.overall == "PASS"
assert edge_calculated > edge_threshold
assert order_placed == True
assert position_size > 0
```

---

### Scenario 4: SUSPECT Book (Queue Overflow)

**Description:** Per-ticker queue overflow due to high message rate.

**Setup:**
- WS connection healthy
- High message rate (> 1000 deltas per ticker)
- Queue overflow detected
- Book marked as SUSPECT
- REST snapshot triggered for recovery

**Expected Gate Decisions:**
- **Spot Age Gate:** PASS (spot independent)
- **Book Freshness Gate:** FAIL (SUSPECT state)
- **Liquidity Gate:** FAIL (book in SUSPECT)
- **Data Quality Gate:** FAIL (SUSPECT)
- **Overall Gate:** REJECT (book unreliable)

**Expected System Behavior:**
- Market state marked as SUSPECT
- REST snapshot triggered immediately
- Pending deltas replayed after snapshot
- No signals until book returns to GOOD
- Agent grid logs "[GATE-REJECT] book_suspect: queue_overflow"

**Test Assertions:**
```python
assert agent.signal_generated == False
assert market_state.book_consistency == "SUSPECT"
assert market_state.suspect_reason == "queue_overflow"
assert gate_decision.overall == "REJECT"
assert rest_snapshot_triggered == True
```

---

### Scenario 5: High Latency (Slow WS)

**Description:** WebSocket messages delayed (high latency).

**Setup:**
- WS connection established
- Message latency > 5 seconds
- Book aging faster than updates
- Spot fresh

**Expected Gate Decisions:**
- **Spot Age Gate:** PASS (spot fresh)
- **Book Freshness Gate:** FAIL (book stale due to latency)
- **Liquidity Gate:** PASS (if book has data)
- **Data Quality Gate:** WARN (latency high, book may be stale)
- **Overall Gate:** REJECT (book too stale for safe pricing)

**Expected System Behavior:**
- WS bridge logs "[WS-LATENCY] latency > 5s, book may be stale"
- Gate rejects due to book freshness
- No signals generated
- Consider switching to REST fallback if WS latency persists

**Test Assertions:**
```python
assert agent.signal_generated == False
assert ws_bridge.latency > 5.0
assert gate_decision.book_freshness == "FAIL"
assert gate_decision.overall == "REJECT"
```

---

### Scenario 6: One-Sided Book (No Bids or No Asks)

**Description:** Book has only one side (bids or asks, not both).

**Setup:**
- WS connection healthy
- Spot fresh
- Book has asks but no bids (or vice versa)
- Edge calculation may be unreliable

**Expected Gate Decisions:**
- **Spot Age Gate:** PASS (spot fresh)
- **Book Freshness Gate:** PASS (book fresh)
- **Liquidity Gate:** FAIL (one-sided book)
- **Data Quality Gate:** WARN (one-sided, may be stale)
- **Overall Gate:** REJECT (insufficient liquidity)

**Expected System Behavior:**
- Agent grid logs "[GATE-REJECT] one_sided_book: no_bids"
- No signals generated
- Continue monitoring for dual-sided book

**Test Assertions:**
```python
assert agent.signal_generated == False
assert len(market_state.bids) == 0 or len(market_state.asks) == 0
assert gate_decision.liquidity == "FAIL"
assert gate_decision.overall == "REJECT"
```

---

### Scenario 7: Edge Below Threshold

**Description:** All gates pass except edge is too small.

**Setup:**
- WS healthy
- Spot fresh
- Book dual-sided with good liquidity
- Edge calculated but below minimum threshold

**Expected Gate Decisions:**
- **Spot Age Gate:** PASS
- **Book Freshness Gate:** PASS
- **Liquidity Gate:** PASS
- **Data Quality Gate:** PASS
- **Edge Gate:** FAIL (edge < threshold)
- **Overall Gate:** REJECT (edge insufficient)

**Expected System Behavior:**
- Agent calculates edge but rejects signal
- No order placed
- Agent grid logs "[GATE-REJECT] edge_insufficient: edge=0.5%, threshold=1.0%"

**Test Assertions:**
```python
assert agent.signal_generated == False
assert edge_calculated < edge_threshold
assert gate_decision.edge == "FAIL"
assert gate_decision.overall == "REJECT"
assert order_placed == False
```

---

### Scenario 8: Risk Budget Exhausted

**Description:** All gates pass but risk budget is exhausted.

**Setup:**
- WS healthy
- Spot fresh
- Book dual-sided with good edge
- Risk budget at 100% utilization

**Expected Gate Decisions:**
- **Spot Age Gate:** PASS
- **Book Freshness Gate:** PASS
- **Liquidity Gate:** PASS
- **Data Quality Gate:** PASS
- **Edge Gate:** PASS
- **Risk Gate:** FAIL (budget exhausted)
- **Overall Gate:** REJECT (no risk capacity)

**Expected System Behavior:**
- Agent calculates signal but rejects due to risk
- No order placed
- Risk budget remains at 100%
- Agent grid logs "[GATE-REJECT] risk_budget_exhausted: utilization=100%"

**Test Assertions:**
```python
assert agent.signal_generated == False
assert risk_env.utilization() == 1.0
assert gate_decision.risk == "FAIL"
assert gate_decision.overall == "REJECT"
assert order_placed == False
```

---

## Test Implementation Approach

### Pytest Fixtures (conftest.py)

```python
import pytest
import os

# Ensure 15m mode for all tests
@pytest.fixture(autouse=True)
def set_15m_mode():
    os.environ['MERID_RUNTIME_MODE'] = '15m_live'
    os.environ['MERID_PROFILE'] = 'kalshi_crypto_15m_v2'
    yield
    # Cleanup after test

@pytest.fixture
def mock_ws_bridge():
    """Mock WS bridge for scenario testing."""
    from unittest.mock import Mock
    bridge = Mock()
    bridge.connection_state = "CONNECTED"
    bridge.latency = 0.1
    return bridge

@pytest.fixture
def mock_spot_service():
    """Mock spot service for scenario testing."""
    from unittest.mock import Mock
    spot = Mock()
    spot.last_update_age = 5.0  # seconds
    return spot

@pytest.fixture
def mock_market_state():
    """Mock market state for scenario testing."""
    from unittest.mock import Mock
    state = Mock()
    state.book_consistency = "GOOD"
    state.bids = [[99, 10], [98, 20]]
    state.asks = [[101, 10], [102, 20]]
    state.last_update_ts = time.time()
    return state

@pytest.fixture
def mock_agent_grid():
    """Mock agent grid for scenario testing."""
    from unittest.mock import Mock
    grid = Mock()
    grid._agents = []
    return grid
```

### Test Example (test_ws_scenarios.py)

```python
def test_ws_down_scenario(mock_ws_bridge, mock_market_state, mock_agent_grid):
    """Test gate decisions when WebSocket is down."""
    # Setup: WS disconnected
    mock_ws_bridge.connection_state = "DISCONNECTED"
    mock_market_state.book_consistency = "SUSPECT"
    mock_market_state.last_update_ts = time.time() - 100  # 100s old
    
    # Run gate checks
    gate_decision = evaluate_gates(
        ws_bridge=mock_ws_bridge,
        market_state=mock_market_state,
        spot_age=5.0,  # spot fresh
    )
    
    # Assertions
    assert gate_decision.spot_age == "PASS"
    assert gate_decision.book_freshness == "FAIL"
    assert gate_decision.liquidity == "FAIL"
    assert gate_decision.data_quality == "FAIL"
    assert gate_decision.overall == "REJECT"
    assert gate_decision.reason == "book_stale"
```

---

## Running the Tests

```bash
# Run all 15m scenario tests
pytest tests/15m_scenario_tests/ -v

# Run specific scenario test
pytest tests/15m_scenario_tests/test_ws_scenarios.py::test_ws_down_scenario -v

# Run with coverage
pytest tests/15m_scenario_tests/ --cov=merid --cov-report=html
```

---

## Integration with CI

Add to CI pipeline:

```yaml
- name: Run 15m Scenario Tests
  run: |
    export MERID_RUNTIME_MODE=15m_live
    export MERID_PROFILE=kalshi_crypto_15m_v2
    pytest tests/15m_scenario_tests/ -v
```

---

## Future Scenarios to Add

- **Market Expiring Soon:** Market < 2 minutes to expiry
- **Position Limit Reached:** Max positions per asset
- **Bankroll Low:** Insufficient equity for new position
- **REST Fallback Mode:** WS down, REST active
- **Spot Service Restart:** Spot service restarts during operation
- **Multiple Markets:** Gate decisions across multiple assets simultaneously

---

**End of 15m Scenario Tests Design**
