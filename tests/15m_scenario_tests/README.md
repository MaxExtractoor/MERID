# 15m Stack Scenario Tests

**Purpose:** Validate gate decisions and system behavior under critical scenarios for the 15m Kalshi crypto stack.

**Contract:** These tests validate the behavior defined in `docs/kalshi_15m_stack.md` for the canonical 15m stack.

**Runtime Mode:** All tests run under `MERID_RUNTIME_MODE=15m_live`.

---

## Overview

The 15m scenario tests validate that the 15m stack makes correct gate decisions under various operational conditions. These tests ensure that:

- The system rejects signals when data is unreliable (WS down, spot stale, SUSPECT book)
- The system accepts signals when conditions are healthy (fresh data, good edge, sufficient liquidity)
- Gate decisions are deterministic and well-documented

**Test Categories:**
- **WebSocket Scenarios:** WS down, high latency, reconnect, healthy
- **Spot Scenarios:** Spot stale, spot fresh, spot service restart, spot missing
- **Orderbook Scenarios:** Dual-sided book, one-sided book, SUSPECT book, queue overflow, wide spread

---

## Prerequisites

- Python 3.10+
- pytest
- pytest-cov (for coverage reports)
- MERID codebase with `docs/kalshi_15m_stack.md` audit document

---

## Installation

```bash
# Install pytest and coverage
pip install pytest pytest-cov

# Install from requirements.txt if available
pip install -r requirements.txt
```

---

## Running the Tests

### Run All 15m Scenario Tests

```bash
# From repository root
pytest tests/15m_scenario_tests/ -v

# With detailed output
pytest tests/15m_scenario_tests/ -vv

# With coverage report
pytest tests/15m_scenario_tests/ --cov=merid --cov-report=html
```

### Run Specific Test Category

```bash
# WebSocket scenarios only
pytest tests/15m_scenario_tests/test_ws_scenarios.py -v

# Spot scenarios only
pytest tests/15m_scenario_tests/test_spot_scenarios.py -v

# Orderbook scenarios only
pytest tests/15m_scenario_tests/test_book_scenarios.py -v
```

### Run Specific Test

```bash
# Run specific test
pytest tests/15m_scenario_tests/test_ws_scenarios.py::test_ws_down_scenario -v

# Run with specific marker (if markers are added)
pytest tests/15m_scenario_tests/ -m "ws" -v
```

### Run in Parallel (for speed)

```bash
# Install pytest-xdist
pip install pytest-xdist

# Run tests in parallel
pytest tests/15m_scenario_tests/ -n auto -v
```

---

## Test Descriptions

### WebSocket Scenarios (`test_ws_scenarios.py`)

| Test | Description | Expected Outcome |
|------|-------------|-----------------|
| `test_ws_down_scenario` | WS disconnected, book stale | REJECT (book_stale) |
| `test_ws_high_latency_scenario` | WS connected but high latency (>5s) | REJECT (book_stale) |
| `test_ws_healthy_scenario` | WS healthy, low latency | PASS (if other gates pass) |
| `test_ws_reconnect_scenario` | WS reconnecting → reconnected | REJECT → PASS |

### Spot Scenarios (`test_spot_scenarios.py`)

| Test | Description | Expected Outcome |
|------|-------------|-----------------|
| `test_spot_stale_scenario` | Spot > 60s old | REJECT (spot_stale) |
| `test_spot_fresh_scenario` | Spot < 30s old | PASS (if other gates pass) |
| `test_spot_boundary_30s_scenario` | Spot exactly 30s old | PASS (boundary) |
| `test_spot_boundary_60s_scenario` | Spot exactly 60s old | REJECT (hard fail) |
| `test_spot_service_restart_scenario` | Spot service restarting → restarted | REJECT → PASS |
| `test_spot_missing_scenario` | Spot data completely missing | REJECT (spot_stale) |

### Orderbook Scenarios (`test_book_scenarios.py`)

| Test | Description | Expected Outcome |
|------|-------------|-----------------|
| `test_dual_sided_book_good_edge_scenario` | Healthy dual-sided book, good edge | PASS |
| `test_one_sided_book_no_bids_scenario` | Book has asks but no bids | REJECT (insufficient_liquidity) |
| `test_one_sided_book_no_asks_scenario` | Book has bids but no asks | REJECT (insufficient_liquidity) |
| `test_suspect_book_queue_overflow_scenario` | SUSPECT book due to queue overflow | REJECT (book_suspect) |
| `test_suspect_book_recovery_scenario` | SUSPECT → GOOD recovery | REJECT → PASS |
| `test_book_stale_scenario` | Book > 10s old | REJECT (book_stale) |
| `test_low_liquidity_scenario` | Book has small quantities | PASS (fixture limitation) |
| `test_wide_spread_scenario` | Wide spread, low edge | REJECT (edge_insufficient) |

---

## Gate Decision Logic

The tests validate the following gate decision logic:

### Gates Evaluated

1. **Spot Age Gate:** PASS if spot < 60s, FAIL otherwise
2. **Book Freshness Gate:** PASS if book < 10s old, FAIL otherwise
3. **Liquidity Gate:** PASS if book has both bids and asks, FAIL otherwise
4. **Data Quality Gate:** PASS if book_consistency == "GOOD", FAIL otherwise
5. **Edge Gate:** PASS if edge >= threshold, FAIL otherwise
6. **Risk Gate:** PASS if risk budget has capacity, FAIL otherwise

### Overall Gate Decision

- **PASS:** All individual gates pass
- **REJECT:** Any individual gate fails (with specific reason)

### Failure Reasons

- `spot_stale`: Spot age gate failed
- `book_stale`: Book freshness gate failed
- `insufficient_liquidity`: Liquidity gate failed
- `book_suspect`: Data quality gate failed (SUSPECT state)
- `edge_insufficient`: Edge gate failed
- `risk_budget_exhausted`: Risk gate failed

---

## Fixtures

The test suite uses the following fixtures (defined in `conftest.py`):

### Auto-Use Fixtures

- `set_15m_mode`: Automatically sets `MERID_RUNTIME_MODE=15m_live` and `MERID_PROFILE=kalshi_crypto_15m_v2` for all tests

### Mock Fixtures

- `mock_ws_bridge`: Mock WebSocket bridge with configurable state
- `mock_spot_service`: Mock spot service with configurable age
- `mock_market_state`: Mock market state with configurable book data
- `mock_agent`: Mock agent for testing signal generation
- `mock_risk_env`: Mock risk environment for testing risk gates
- `gate_decision`: Mock gate decision object
- `evaluate_gates`: Helper function to evaluate gate decisions based on scenario conditions

---

## Adding New Tests

### Step 1: Define the Scenario

Add the scenario description to `tests/15m_scenario_tests.md` with:
- Description
- Setup conditions
- Expected gate decisions
- Expected system behavior
- Test assertions

### Step 2: Implement the Test

Add the test function to the appropriate test file:
- `test_ws_scenarios.py` for WebSocket scenarios
- `test_spot_scenarios.py` for spot scenarios
- `test_book_scenarios.py` for orderbook scenarios

Example:

```python
def test_new_scenario(mock_ws_bridge, mock_market_state, mock_spot_service, evaluate_gates):
    """Test gate decisions for new scenario.
    
    Expected:
    - Spot Age Gate: PASS
    - Book Freshness Gate: PASS
    - Overall Gate: PASS
    """
    # Setup scenario conditions
    mock_ws_bridge.connection_state = "CONNECTED"
    mock_market_state.book_consistency = "GOOD"
    mock_spot_service.last_update_age = 5.0
    
    # Evaluate gates
    gate_decision = evaluate_gates(
        ws_bridge=mock_ws_bridge,
        market_state=mock_market_state,
        spot_age=mock_spot_service.last_update_age,
    )
    
    # Assertions
    assert gate_decision.overall == "PASS"
```

### Step 3: Run the Test

```bash
pytest tests/15m_scenario_tests/test_<category>_scenarios.py::test_new_scenario -v
```

### Step 4: Update Documentation

Update this README with the new test in the appropriate table.

---

## CI Integration

Add to your CI pipeline (e.g., GitHub Actions, GitLab CI):

```yaml
- name: Run 15m Scenario Tests
  run: |
    export MERID_RUNTIME_MODE=15m_live
    export MERID_PROFILE=kalshi_crypto_15m_v2
    pytest tests/15m_scenario_tests/ -v --cov=merid --cov-report=xml
  env:
    MERID_RUNTIME_MODE: 15m_live
    MERID_PROFILE: kalshi_crypto_15m_v2
```

---

## Troubleshooting

### Tests Fail with Import Errors

**Issue:** Tests fail to import modules.

**Solution:** Ensure you're running from the repository root and the `merid` package is in your Python path:

```bash
cd /path/to/MERID
pytest tests/15m_scenario_tests/ -v
```

### Tests Fail with Legacy Module Detection

**Issue:** Tests fail because legacy modules are detected.

**Solution:** Ensure the import kill-switch in `main_15m_lean.py` is not interfering with test imports. The test fixtures set `MERID_RUNTIME_MODE=15m_live` but do not load the full FastAPI app.

### Gate Decision Logic Mismatch

**Issue:** Test assertions don't match actual gate decision logic in production.

**Solution:** Update the `evaluate_gates` fixture in `conftest.py` to match the actual gate decision logic in `agent_grid_15m.py`. The fixture is a simplified version for testing purposes.

---

## Future Enhancements

- Add integration tests that use actual 15m stack components (not mocks)
- Add performance tests to validate gate decision latency
- Add stress tests with high message rates
- Add tests for edge cases (market expiry, position limits, etc.)
- Add tests for multi-asset scenarios (gate decisions across BTC, ETH, SOL, XRP, DOGE)

---

## Related Documentation

- `docs/kalshi_15m_stack.md` - Canonical 15m stack definition
- `docs/15m_stack_audit.md` - Original audit report
- `scripts/validate_15m_stack.py` - CI validation script for 15m stack

---

**End of README**
