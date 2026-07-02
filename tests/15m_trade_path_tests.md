# 15m Trade Path Tests

**Purpose:** Validate the end-to-end trade path from signal generation through order placement, fill confirmation, and PnL calculation for the 15m Kalshi crypto stack.

**Contract:** These tests validate that a 15m BTC/ETH contract can successfully traverse the complete trade path under tightly controlled conditions.

**Runtime Mode:** All tests run under `MERID_RUNTIME_MODE=15m_live`.

---

## Test Scope

The trade path tests validate the following stages:

1. **Signal Generation** - Agent generates a trading signal based on market data
2. **Candidate Selection** - Signal passes all gate checks and becomes a trade candidate
3. **Order Placement** - Order router places the order with Kalshi
4. **Fill Confirmation** - Order is filled and confirmed via fills ledger
5. **PnL Calculation** - PnL is calculated and risk budget is updated

This complements the scenario tests by validating the happy path end-to-end, while scenario tests validate individual gate decisions under failure conditions.

---

## Test Architecture

```
tests/
├── 15m_trade_path_tests/
│   ├── __init__.py
│   ├── conftest.py                 # Pytest fixtures for trade path tests
│   ├── test_signal_generation.py   # Signal generation tests
│   ├── test_order_placement.py     # Order placement tests
│   ├── test_fill_confirmation.py   # Fill confirmation tests
│   └── test_pnl_calculation.py     # PnL calculation tests
```

---

## Trade Path Stages

### Stage 1: Signal Generation

**Input:**
- Fresh spot price (< 30s)
- Fresh orderbook (< 10s, dual-sided, GOOD consistency)
- Positive edge (> threshold)
- Risk budget has capacity

**Expected Output:**
- Agent generates signal
- Signal includes: asset, market_id, direction (YES/NO), contracts, price_cents, edge_pct

**Validation:**
- Signal is generated
- Signal contains all required fields
- Signal direction matches edge calculation
- Contract size respects risk budget

### Stage 2: Candidate Selection

**Input:**
- Generated signal from Stage 1
- Gate decision (all gates PASS)

**Expected Output:**
- Signal becomes trade candidate
- Candidate is queued for order placement
- Candidate includes all signal fields plus timestamp

**Validation:**
- Gate decision is PASS
- Candidate is created
- Candidate timestamp is recent
- Candidate matches signal fields

### Stage 3: Order Placement

**Input:**
- Trade candidate from Stage 2
- Kalshi client connected

**Expected Output:**
- Order is placed with Kalshi
- Order ID is returned
- Order status is PENDING or OPEN

**Validation:**
- Order is placed successfully
- Order ID is valid
- Order parameters match candidate
- Order status is valid

### Stage 4: Fill Confirmation

**Input:**
- Placed order from Stage 3
- Kalshi fills poller running

**Expected Output:**
- Order is filled
- Fill is recorded in fills ledger
- Fill includes: order_id, side, contracts, price_cents, timestamp

**Validation:**
- Fill is confirmed
- Fill matches order parameters
- Fill is recorded in ledger
- Fill timestamp is recent

### Stage 5: PnL Calculation

**Input:**
- Confirmed fill from Stage 4
- Market settlement price

**Expected Output:**
- PnL is calculated
- Risk budget is updated
- Position is tracked

**Validation:**
- PnL is calculated correctly
- Risk budget is updated
- Position is tracked correctly
- PnL matches expected value

---

## Happy Path Test: BTC/ETH Contract

### Test: `test_btc_eth_happy_path`

**Setup:**
- Asset: BTC
- Market: BTC-15m-2026-06-05
- Spot: $65,000 (fresh)
- Orderbook: dual-sided, GOOD, mid at 65%
- Edge: 2% (above 1% threshold)
- Risk budget: 30% utilized (has capacity)
- Direction: YES (bullish)

**Expected Flow:**
1. Agent generates signal for YES contracts
2. All gates pass (spot fresh, book fresh, liquidity, data quality, edge, risk)
3. Signal becomes candidate
4. Order placed for 10 YES contracts at 65 cents
5. Order filled at 65 cents
6. PnL calculated based on settlement

**Assertions:**
```python
# Stage 1: Signal Generation
assert signal is not None
assert signal.asset == "BTC"
assert signal.direction == "YES"
assert signal.contracts > 0
assert signal.edge_pct >= 1.0

# Stage 2: Candidate Selection
assert candidate is not None
assert gate_decision.overall == "PASS"
assert candidate.market_id == signal.market_id

# Stage 3: Order Placement
assert order is not None
assert order.order_id is not None
assert order.status in ["PENDING", "OPEN"]
assert order.contracts == signal.contracts

# Stage 4: Fill Confirmation
assert fill is not None
assert fill.order_id == order.order_id
assert fill.contracts == order.contracts
assert fill.price_cents == order.price_cents

# Stage 5: PnL Calculation
assert pnl is not None
assert risk_env.utilization() > 0.3  # Risk budget increased
assert position.size == fill.contracts
```

---

## Edge Cases to Test

### 1. Signal Generated But Gate Rejects

**Setup:**
- Signal generated
- Edge below threshold

**Expected:**
- Signal generated
- Gate decision REJECT
- No candidate created
- No order placed

### 2. Order Placed But Not Filled

**Setup:**
- Order placed
- Market expires before fill

**Expected:**
- Order placed
- Order status EXPIRED
- No fill recorded
- No PnL calculated

### 3. Fill Partial

**Setup:**
- Order for 10 contracts
- Only 5 contracts filled

**Expected:**
- Order placed
- Partial fill recorded
- PnL calculated for filled portion
- Remaining order cancelled

### 4. Risk Budget Exhausted Mid-Trade

**Setup:**
- Risk budget at 90%
- Order placed
- Another order attempts to place

**Expected:**
- First order placed
- Second order rejected (risk gate FAIL)
- Risk budget updated after first fill

### 5. Market Settlement

**Setup:**
- Fill confirmed
- Market settles at YES=100

**Expected:**
- PnL calculated at settlement
- Position closed
- Risk budget released

---

## Test Fixtures

### Pytest Fixtures (conftest.py)

```python
@pytest.fixture(autouse=True)
def set_15m_mode():
    """Ensure all tests run in 15m live mode."""
    os.environ['MERID_RUNTIME_MODE'] = '15m_live'
    os.environ['MERID_PROFILE'] = 'kalshi_crypto_15m_v2'
    yield
    # Cleanup

@pytest.fixture
def mock_agent():
    """Mock agent for signal generation."""
    agent = Mock()
    agent.asset = "BTC"
    agent.market_id = "BTC-15m-2026-06-05"
    agent.enabled = True
    return agent

@pytest.fixture
def mock_market_state():
    """Mock market state with healthy book."""
    state = Mock()
    state.book_consistency = "GOOD"
    state.bids = [[64, 100], [63, 200]]
    state.asks = [[66, 100], [67, 200]]
    state.mid_cents = 65
    state.last_update_ts = time.time() - 1
    return state

@pytest.fixture
def mock_spot_service():
    """Mock spot service with fresh data."""
    spot = Mock()
    spot.last_update_age = 5.0
    spot.get_price = Mock(return_value=65000.0)
    return spot

@pytest.fixture
def mock_risk_env():
    """Mock risk environment with capacity."""
    risk = Mock()
    risk.utilization = Mock(return_value=0.3)
    risk.has_capacity = Mock(return_value=True)
    risk.update_position = Mock()
    return risk

@pytest.fixture
def mock_kalshi_client():
    """Mock Kalshi client for order placement."""
    client = Mock()
    client.place_order = Mock(return_value="order_123")
    return client

@pytest.fixture
def mock_fills_ledger():
    """Mock fills ledger for fill tracking."""
    ledger = Mock()
    ledger.record_fill = Mock()
    ledger.get_fills = Mock(return_value=[])
    return ledger
```

---

## Running the Tests

```bash
# Run all trade path tests
pytest tests/15m_trade_path_tests/ -v

# Run specific stage tests
pytest tests/15m_trade_path_tests/test_signal_generation.py -v
pytest tests/15m_trade_path_tests/test_order_placement.py -v

# Run happy path test
pytest tests/15m_trade_path_tests/test_signal_generation.py::test_btc_eth_happy_path -v

# Run with coverage
pytest tests/15m_trade_path_tests/ --cov=merid --cov-report=html
```

---

## Integration with Scenario Tests

The trade path tests build on the scenario tests:

- **Scenario tests** validate individual gate decisions under failure conditions
- **Trade path tests** validate the complete happy path end-to-end

Both test suites run under `MERID_RUNTIME_MODE=15m_live` and use the same mock fixtures for consistency.

---

## Future Enhancements

- Add multi-asset trade path tests (BTC, ETH, SOL, XRP, DOGE)
- Add concurrent order placement tests
- Add order cancellation tests
- Add market expiry handling tests
- Add settlement PnL validation tests
- Add integration tests with actual Kalshi sandbox environment

---

## Related Documentation

- `docs/kalshi_15m_stack.md` - Canonical 15m stack definition
- `tests/15m_scenario_tests.md` - Scenario test design document
- `tests/15m_scenario_tests/README.md` - Scenario test suite documentation
- `docs/15m_health_snapshot.md` - Health snapshot documentation

---

**End of 15m Trade Path Tests Design**
