# Pass 9 Test Fixes Summary

## Structural Test Fixes Applied

### 1. Added FastAPI TestClient Infrastructure
**File:** `tests/scenario/test_pass9_scenarios.py`

Added at top of file:
```python
from fastapi.testclient import TestClient

# Import the FastAPI app
try:
    from web.main import app
except ImportError:
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))
    from web.main import app

@pytest.fixture(scope="module")
def client():
    """FastAPI TestClient fixture for scenario tests."""
    return TestClient(app)
```

### 2. Fixed Scenario B Tests (3 tests)

All three tests now use the `client` fixture and make actual HTTP calls:

**test_fail_closed_returns_503**
- Calls `client.post("/api/v1/kalshi/orders", ...)`
- Asserts 503 status when router unavailable
- Verifies error message content

**test_no_rest_fallback_in_live**
- Mocks `KalshiRestClient.create_order` to verify it's NOT called
- Calls orders endpoint with router failure
- Asserts 503 status and no REST client calls

**test_kill_switch_triggered**
- Mocks kill_switch and triggers endpoint
- Verifies `trigger.called` is True
- Asserts severity="critical" and "contract violation" in reason

### 3. Fixed Scenario D Tests (2 tests)

**test_fix_endpoint_blocked_in_live**
- Uses `client.post("/api/v1/kalshi/fix/orders", ...)`
- Asserts 403 status in LIVE mode
- Verifies error message contains "fix", "disabled", or "canonical"

**test_ct_api_blocked_in_live**
- Uses `client.get("/api/v1/kalshi/continuous-trader/status")`
- Asserts 403 status in LIVE mode
- Verifies error message contains "continuous trader" or "disabled"

### 4. Fixed Import Paths

Changed all patches from:
```python
"merid.trading.trade_mode.get_trade_mode"  # WRONG
```

To:
```python
"trading.trade_mode.get_trade_mode"  # CORRECT
```

The module is at `trading/trade_mode.py`, not `merid/trading/trade_mode.py`.

## Expected Test Results

| Category | Tests | Expected Pass | Notes |
|----------|-------|---------------|-------|
| Scenario A | 3 | 3 | All logic-based, already passing |
| Scenario B | 3 | 3 | Now using TestClient |
| Scenario C | 3 | 3 | All logic-based, already passing |
| Scenario D | 4 | 4 | Now using TestClient |
| Scenario E | 4 | 4 | All logic-based, already passing |
| **Total** | **17** | **17** | **100%** |

## Remaining Work for Pass 10

Once tests are passing:

1. **Architecture Consolidation**
   - Single executor verification
   - Risk model invariant checks
   - Universal guards confirmation

2. **UI/UX Upstream Sweep**
   - SIM/PAPER/LIVE clarity in UI
   - Risk settings surfaces
   - Error and guard feedback

3. **Downstream Observability**
   - Logging consistency
   - Metrics/alerts
   - Runbook documentation

## Next Steps

1. Run `py -m pytest tests/scenario/test_pass9_scenarios.py -v` to verify 17/17 passing
2. If any tests still fail, check:
   - App import path is correct (`from web.main import app`)
   - All patches use correct module paths
   - Endpoints exist in the actual API

3. Proceed to Pass 10 for integration and UX/ops sweep
