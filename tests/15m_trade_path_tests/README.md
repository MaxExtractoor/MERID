# 15m Trade Path Tests

**Purpose:** Validate the end-to-end trade path from signal generation through order placement, fill confirmation, and PnL calculation for the 15m Kalshi crypto stack.

**Contract:** These tests validate that a 15m BTC/ETH contract can successfully traverse the complete trade path under tightly controlled conditions.

**Runtime Mode:** All tests run under `MERID_RUNTIME_MODE=15m_live`.

---

## Overview

The 15m trade path tests validate the complete trading flow, ensuring that all stages work correctly together:

1. **Signal Generation** - Agent generates a trading signal based on market data
2. **Candidate Selection** - Signal passes all gate checks and becomes a trade candidate
3. **Order Placement** - Order router places the order with Kalshi
4. **Fill Confirmation** - Order is filled and confirmed via fills ledger
5. **PnL Calculation** - PnL is calculated and risk budget is updated

This complements the scenario tests (`tests/15m_scenario_tests/`) by validating the happy path end-to-end, while scenario tests validate individual gate decisions under failure conditions.

---

## Test Structure

```
tests/15m_trade_path_tests/
├── __init__.py
├── conftest.py                 # Pytest fixtures for trade path tests
├── test_signal_generation.py   # Signal generation tests (8 tests)
├── test_order_placement.py     # Order placement tests (8 tests)
├── test_fill_confirmation.py   # Fill confirmation tests (9 tests)
├── test_pnl_calculation.py     # PnL calculation tests (9 tests)
└── test_happy_path.py          # End-to-end happy path tests (5 tests)
```

---

## Test Summary

| Test File | Tests | Description |
|-----------|-------|-------------|
| `test_signal_generation.py` | 8 | Signal generation for various conditions |
| `test_order_placement.py` | 8 | Order placement with Kalshi |
| `test_fill_confirmation.py` | 9 | Fill confirmation and ledger recording |
| `test_pnl_calculation.py` | 9 | PnL calculation and risk budget updates |
| `test_happy_path.py` | 5 | End-to-end happy path validation |
| **Total** | **39** | **Complete trade path coverage** |

---

## Running the Tests

### Run All Trade Path Tests

```bash
# From repository root
pytest tests/15m_trade_path_tests/ -v

# With detailed output
pytest tests/15m_trade_path_tests/ -vv

# With coverage report
pytest tests/15m_trade_path_tests/ --cov=merid --cov-report=html
```

### Run Specific Stage Tests

```bash
# Signal generation tests only
pytest tests/15m_trade_path_tests/test_signal_generation.py -v

# Order placement tests only
pytest tests/15m_trade_path_tests/test_order_placement.py -v

# Fill confirmation tests only
pytest tests/15m_trade_path_tests/test_fill_confirmation.py -v

# PnL calculation tests only
pytest tests/15m_trade_path_tests/test_pnl_calculation.py -v

# Happy path tests only
pytest tests/15m_trade_path_tests/test_happy_path.py -v
```

### Run Specific Test

```bash
# Run specific test
pytest tests/15m_trade_path_tests/test_happy_path.py::test_btc_eth_happy_path -v

# Run with specific marker (if markers are added)
pytest tests/15m_trade_path_tests/ -m "happy_path" -v
```

### Run in Parallel (for speed)

```bash
# Install pytest-xdist
pip install pytest-xdist

# Run tests in parallel
pytest tests/15m_trade_path_tests/ -n auto -v
```

---

## Test Descriptions

### Signal Generation Tests (`test_signal_generation.py`)

| Test | Description |
|------|-------------|
| `test_signal_generation_happy_path` | Signal generation under healthy conditions |
| `test_signal_generation_bullish_edge` | Signal generation for bullish edge (YES direction) |
| `test_signal_generation_bearish_edge` | Signal generation for bearish edge (NO direction) |
| `test_signal_generation_edge_below_threshold` | Signal generation when edge is below threshold |
| `test_signal_generation_multiple_assets` | Signal generation for multiple assets (BTC, ETH, SOL, XRP, DOGE) |
| `test_signal_timestamp_freshness` | Signal timestamp is fresh (within last second) |
| `test_signal_contract_size_respects_risk` | Contract size respects risk budget |
| `test_signal_market_id_format` | Signal market_id follows correct format |

### Order Placement Tests (`test_order_placement.py`)

| Test | Description |
|------|-------------|
| `test_order_placement_happy_path` | Order placement under happy path conditions |
| `test_order_placement_gate_reject` | Order not placed when gate decision rejects |
| `test_order_placement_multiple_contracts` | Order placement with multiple contract sizes |
| `test_order_placement_yes_direction` | Order placement for YES direction |
| `test_order_placement_no_direction` | Order placement for NO direction |
| `test_order_placement_different_assets` | Order placement for different assets |
| `test_order_placement_price_validation` | Order price is within valid range (1-99 cents) |
| `test_order_placement_timestamp_freshness` | Order timestamp is fresh |
| `test_order_placement_client_called` | Kalshi client called with correct parameters |

### Fill Confirmation Tests (`test_fill_confirmation.py`)

| Test | Description |
|------|-------------|
| `test_fill_confirmation_happy_path` | Fill confirmation under happy path conditions |
| `test_fill_confirmation_partial_fill` | Partial fill scenario (5 of 10 contracts) |
| `test_fill_confirmation_multiple_fills` | Multiple fills for the same order |
| `test_fill_confirmation_yes_direction` | Fill confirmation for YES direction |
| `test_fill_confirmation_no_direction` | Fill confirmation for NO direction |
| `test_fill_confirmation_timestamp_freshness` | Fill timestamp is fresh |
| `test_fill_confirmation_ledger_recording` | Fill recorded in fills ledger |
| `test_fill_confirmation_different_assets` | Fill confirmation for different assets |
| `test_fill_confirmation_price_matching` | Fill price matches order price |

### PnL Calculation Tests (`test_pnl_calculation.py`)

| Test | Description |
|------|-------------|
| `test_pnl_calculation_yes_settlement` | PnL calculation for YES direction at settlement (YES=100) |
| `test_pnl_calculation_no_settlement` | PnL calculation for NO direction at settlement (NO=0) |
| `test_pnl_calculation_profitable_trade` | PnL calculation for profitable trade |
| `test_pnl_calculation_loss_trade` | PnL calculation for losing trade |
| `test_pnl_calculation_breakeven_trade` | PnL calculation for breakeven trade |
| `test_pnl_calculation_multiple_contracts` | PnL calculation with different contract sizes |
| `test_pnl_calculation_risk_budget_update` | Risk budget updated after PnL calculation |
| `test_pnl_calculation_different_assets` | PnL calculation for different assets |
| `test_pnl_calculation_position_tracking` | Position tracked correctly after PnL calculation |

### Happy Path Tests (`test_happy_path.py`)

| Test | Description |
|------|-------------|
| `test_btc_eth_happy_path` | Complete happy path for BTC contract (5 stages validated) |
| `test_eth_happy_path` | Complete happy path for ETH contract |
| `test_no_direction_happy_path` | Complete happy path for NO direction (bearish) |
| `test_multi_asset_happy_path` | Happy path for multiple assets (BTC, ETH, SOL, XRP, DOGE) |
| `test_risk_budget_exhausted_prevents_trade` | Trade prevented when risk budget exhausted |

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

## Fixtures

The test suite uses the following fixtures (defined in `conftest.py`):

### Auto-Use Fixtures

- `set_15m_mode`: Automatically sets `MERID_RUNTIME_MODE=15m_live` and `MERID_PROFILE=kalshi_crypto_15m_v2` for all tests

### Mock Fixtures

- `mock_agent`: Mock agent for signal generation
- `mock_market_state`: Mock market state with healthy book
- `mock_spot_service`: Mock spot service with fresh data
- `mock_risk_env`: Mock risk environment with capacity
- `mock_kalshi_client`: Mock Kalshi client for order placement
- `mock_fills_ledger`: Mock fills ledger for fill tracking
- `mock_order_router`: Mock order router for order placement

### Gate Decision Fixtures

- `gate_decision_pass`: Mock gate decision with all gates passing
- `gate_decision_fail`: Mock gate decision with edge gate failing

### Helper Fixtures

- `generate_signal`: Helper function to generate a trading signal
- `create_candidate`: Helper function to create a trade candidate
- `place_order`: Helper function to place an order
- `confirm_fill`: Helper function to confirm a fill
- `calculate_pnl`: Helper function to calculate PnL

### Data Classes

- `Signal`: Trading signal dataclass
- `Candidate`: Trade candidate dataclass
- `Order`: Order dataclass
- `Fill`: Fill dataclass
- `Position`: Position dataclass

---

## Example: Happy Path Test

```python
def test_btc_eth_happy_path(
    generate_signal,
    gate_decision_pass,
    create_candidate,
    place_order,
    confirm_fill,
    calculate_pnl,
    mock_kalshi_client,
    mock_fills_ledger,
    mock_risk_env,
):
    """Test complete happy path for BTC/ETH contract."""
    
    # Stage 1: Signal Generation
    signal = generate_signal(
        asset="BTC",
        market_id="BTC-15m-2026-06-05",
        direction="YES",
        contracts=10,
        price_cents=65,
        edge_pct=2.0,
    )
    
    # Stage 2: Candidate Selection
    candidate = create_candidate(signal, gate_decision_pass)
    
    # Stage 3: Order Placement
    order = place_order(candidate, mock_kalshi_client)
    
    # Stage 4: Fill Confirmation
    fill = confirm_fill(order, mock_fills_ledger)
    
    # Stage 5: PnL Calculation
    settlement_price_cents = 100
    position = calculate_pnl(fill, settlement_price_cents, mock_risk_env)
    
    # Assertions for all stages
    assert signal is not None
    assert candidate.gate_decision["overall"] == "PASS"
    assert order.order_id is not None
    assert fill.order_id == order.order_id
    assert position.pnl_cents == (100 - 65) * 10  # 350 cents
```

---

## Integration with Scenario Tests

The trade path tests build on the scenario tests:

- **Scenario tests** (`tests/15m_scenario_tests/`) validate individual gate decisions under failure conditions
- **Trade path tests** (`tests/15m_trade_path_tests/`) validate the complete happy path end-to-end

Both test suites run under `MERID_RUNTIME_MODE=15m_live` and use similar mock fixtures for consistency.

---

## CI Integration

Add to your CI pipeline (e.g., GitHub Actions, GitLab CI):

```yaml
- name: Run 15m Trade Path Tests
  run: |
    export MERID_RUNTIME_MODE=15m_live
    export MERID_PROFILE=kalshi_crypto_15m_v2
    pytest tests/15m_trade_path_tests/ -v --cov=merid --cov-report=xml
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
pytest tests/15m_trade_path_tests/ -v
```

### Tests Fail with Legacy Module Detection

**Issue:** Tests fail because legacy modules are detected.

**Solution:** Ensure the import kill-switch in `main_15m_lean.py` is not interfering with test imports. The test fixtures set `MERID_RUNTIME_MODE=15m_live` but do not load the full FastAPI app.

### Helper Fixture Parameters Mismatch

**Issue:** Helper fixtures (e.g., `place_order`, `confirm_fill`) receive unexpected parameters.

**Solution:** Ensure all required fixtures are included in the test function signature. Check `conftest.py` for the correct fixture signatures.

---

## Future Enhancements

- Add integration tests with actual Kalshi sandbox environment
- Add concurrent order placement tests
- Add order cancellation tests
- Add market expiry handling tests
- Add settlement PnL validation tests
- Add slippage and latency simulation tests
- Add multi-asset portfolio tests

---

## Related Documentation

- `docs/kalshi_15m_stack.md` - Canonical 15m stack definition
- `tests/15m_scenario_tests.md` - Scenario test design document
- `tests/15m_scenario_tests/README.md` - Scenario test suite documentation
- `docs/15m_health_snapshot.md` - Health snapshot documentation
- `tests/15m_trade_path_tests.md` - Trade path test design document

---

**End of README**
