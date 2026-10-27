# RB-2: REST Fallback Fail-Closed (503)

**Alert:** `merid_executor_available == 0` or `merid_guard_trips_total{guard_type="REST_FALLBACK"} > 0`

## Symptoms

- HTTP **503 Service Unavailable** on `/api/v1/kalshi/orders`
- Response: `"Trading system degraded. Order router unavailable..."`
- Log: `"EXECUTOR_FAILURE"` with `fallback_attempted: false`
- Kill switch may trigger automatically
- All trading halted

## Impact

- **Complete trading halt** - no orders can be placed
- System is in fail-closed state (safe)
- Requires operator intervention to restore

## Investigation

### 1. Check Executor Status

```bash
# Check if order_router is importable
python -c "
from merid.event_venues.kalshi.order_router import get_order_router
router = get_order_router()
print(f'Router available: {router is not None}')
"
```

### 2. Review Logs

```bash
# Find executor failure details
grep "EXECUTOR_FAILURE" /var/log/merid/app.log | tail -5

# Check for import errors
grep "ImportError\|ModuleNotFoundError" /var/log/merid/app.log | tail -10

# Check startup logs
grep "Unified Risk Model Enforcement\|STARTUP_ENFORCEMENT" /var/log/merid/startup.log
```

### 3. Check Kill Switch Status

```bash
# Check if kill switch is active
curl http://localhost:9100/metrics | grep merid_kill_switch_active
# 1 = active, 0 = inactive

# Check recent kill switch activations
jq 'select(.event_type == "KILL_SWITCH")' /var/log/merid/app.log | tail -1
```

## Root Causes

| Cause | Indicator | Solution |
|-------|-----------|----------|
| Import error | `ImportError` in logs | Fix import, restart |
| Config violation | `RiskConfigViolationError` | Fix config, restart |
| Missing dependency | `ModuleNotFoundError` | Install deps, restart |
| Circular import | Import hangs then fails | Refactor imports |

## Remediation

### Step 1: Identify Root Cause

```bash
# Try importing manually to see exact error
python -c "from web.main import app" 2>&1

# Check config
python -c "
from merid.config.unified_risk_enforcement import enforce_at_startup
try:
    enforce_at_startup()
    print('Config OK')
except Exception as e:
    print(f'Config error: {e}')
"
```

### Step 2: Fix the Issue

**If import error:**
```bash
# Check missing module
pip install <missing_module>

# Or if circular import, check order in web/main.py
```

**If config violation:**
```bash
# Edit config file
vim config/portfolio_optimizer.yaml

# Reduce max_risk_pct_global to <= 0.02
# Remove max_total_notional_usd for live mode
```

**If dependency issue:**
```bash
# Reinstall dependencies
pip install -e . --force-reinstall

# Or recreate virtualenv
rm -rf venv
python -m venv venv
source venv/bin/activate
pip install -e .
```

### Step 3: Restart Application

```bash
# Graceful shutdown
kill -SIGTERM <merid_pid>

# Or force if stuck
kill -SIGKILL <merid_pid>

# Restart
python -m web.main
```

### Step 4: Verify Startup

```bash
# Check startup logs
tail -f /var/log/merid/startup.log

# Look for:
# - "Unified Risk Model Enforcement" ... "✓"
# - "Phase -1c: Unified risk enforcement"
# - No ERROR or CRITICAL during startup
```

## Verification

```bash
# 1. Health check
curl http://localhost:8000/api/v1/health | jq
# Expected: {"status": "ok", "executor": "available", "mode": "..."}

# 2. Test order placement
curl -X POST http://localhost:8000/api/v1/kalshi/orders \
  -H "Content-Type: application/json" \
  -d '{
    "ticker": "KXBTC-15M",
    "side": "buy",
    "quantity": 1,
    "price": 5000
  }'
# Expected: 200 OK or risk rejection (not 503)

# 3. Check metrics
curl http://localhost:9100/metrics | grep merid_executor_available
# Expected: 1

# 4. Check no kill switch active
curl http://localhost:9100/metrics | grep merid_kill_switch_active
# Expected: 0
```

## If Kill Switch Was Triggered

**DO NOT simply restart** - requires formal reset process:

1. **Verify root cause is fixed** (see Step 2 above)

2. **Run full test suite:**
   ```bash
   pytest tests/scenario/test_pass9_scenarios.py -v
   # Must pass: 17/17
   ```

3. **Run CI invariants:**
   ```bash
   python scripts/ci/check_kalshi_invariants.py
   # Must pass: 8/8
   ```

4. **Manual reset with on-call approval:**
   ```bash
   python -c "
   from merid.risk.kill_switches import get_kill_switch
   ks = get_kill_switch()
   ks.reset(reason='Root cause fixed, tests passing, on-call approval: <NAME>')
   "
   ```

5. **Verify trading resumes:**
   ```bash
   # Place test order
   curl -X POST /api/v1/kalshi/orders ...
   ```

## Resume Criteria

Before declaring system operational:

- [ ] `/health` returns 200 with `executor: available`
- [ ] Test order returns non-503 response
- [ ] Metrics show `merid_executor_available == 1`
- [ ] No ERROR or CRITICAL in startup logs
- [ ] If kill switch triggered: All tests pass (17/17) + on-call approval

## Escalation

**Contact:** #on-call immediately if:
- Kill switch triggered (trading halted)
- Cannot identify root cause
- Multiple restart attempts fail

**Contact:** #platform-engineering if:
- Dependency issues persist
- Import errors unclear
- Circular import suspected

## Related

- Guard location: `web/api/kalshi_api.py:2890`
- Test: `tests/scenario/test_pass9_scenarios.py::test_fail_closed_returns_503`
- CI Invariant: `check_rest_fallback_guard()`
- Kill switch: `merid/risk/kill_switches.py`
