# MERID Go-Live Checklist

**Paper → Live Cutover Guide**

## Pre-Flight Checks

### 1. Configuration Validation

```bash
# Run preflight checks
make preflight

# Inspect risk context
make risk-context
```

### 2. Environment Variables

Trading mode is controlled per-venue via `ModeManager`, not a global env var.

Use `make risk-context` to inspect current system state.

| Setting | Description |
|---------|-------------|
| Venue mode (SIM/PAPER/LIVE) | Set via `/api/v1/pipeline/venue/mode` or `ModeManager` |
| Domain enable/disable | Set via `/api/v1/pipeline/domain/enable` |
| Kill switch | Via `ExecutionGuard` or `/risk/kill-switch/enable` |

### 3. Safety Interlocks

| Setting | Default | Description |
|---------|---------|-------------|
| `MERID_TOTAL_CAPITAL_USD` | 50000 | Total capital across all domains |
| `MERID_CRYPTO_MAX_NOTIONAL_USD` | 25000 | Crypto domain max notional |
| `MERID_CRYPTO_MAX_DAILY_LOSS_USD` | 1000 | Crypto daily loss limit |
| `MERID_EQUITY_MAX_NOTIONAL_USD` | 20000 | Equity domain max notional |
| `MERID_PM_MAX_DAILY_LOSS` | 250 | Prediction market daily loss limit |

---

## Paper Trading Phase

### Step 1: Run Dry-Run

```bash
make preflight
```

This validates:
- [ ] 490 golden path tests pass
- [ ] Readiness auditor passes (24/7 + swarm)
- [ ] Codebase drift audit clean
- [ ] RiskContext snapshot healthy

### Step 2: Extended Paper Test (1-7 days)

Run MERID in paper mode with real market data:

```bash
# Start MeridLoop in observe mode (no execution)
make loop-start

# Or with execution enabled (paper mode by default)
make loop-start-execute
```

Verify:
- [ ] Orders execute correctly (simulated)
- [ ] Position tracking is accurate
- [ ] P&L calculations are correct
- [ ] No errors in logs
- [ ] Circuit breakers don't trip unexpectedly

### Step 3: Review Paper Results

Before going live, ensure:
- [ ] Paper P&L is reasonable (not too good to be true)
- [ ] Slippage estimates are realistic
- [ ] No unexpected errors or warnings

---

## Go-Live Phase

### Step 1: Credential Setup

For each venue you want to trade:

**Kalshi:**
```bash
export KALSHI_API_KEY_ID="your-key"
export KALSHI_PRIVATE_KEY_PATH="/path/to/key.pem"
# OR
export KALSHI_PRIVATE_KEY_PEM="-----BEGIN PRIVATE KEY-----..."
```

**Note:** Polymarket/Augur/PredictIt are **prohibited** by ComplianceRegistry (US compliance).

**Alpaca:**
```bash
export ALPACA_API_KEY="your-key"
export ALPACA_API_SECRET="your-secret"
```

### Step 2: Validate Credentials

```bash
make preflight
curl http://127.0.0.1:8000/api/v1/pipeline/venues | jq
```

All credential errors should be resolved.

### Step 3: Set Conservative Limits

Start with conservative limits:

Risk limits are configured in `merid/settings.py` (Pydantic Settings) or via env vars:

```bash
export MERID_TOTAL_CAPITAL_USD=10000           # Start with reduced capital
export MERID_CRYPTO_MAX_DAILY_LOSS_USD=250     # Tight loss limit
export MERID_PM_MAX_DAILY_LOSS=100             # Small PM loss limit
```

### Step 4: Switch Venue to LIVE

Venue modes are set per-venue via the API or ModeManager:

```bash
# Switch Alpaca to LIVE
curl -X POST http://127.0.0.1:8000/api/v1/pipeline/venue/mode \
  -H "Content-Type: application/json" \
  -d '{"venue": "alpaca", "mode": "live"}'
```

### Step 5: Final Validation

```bash
make risk-context
# Check: kill_switch_active=false, size_scale_factor > 0
curl http://127.0.0.1:8000/api/v1/pipeline/summary | jq
```

### Step 6: Start with Monitoring

```bash
# Start the loop with execution
make loop-start-execute
```

Monitor:
- [ ] First orders execute correctly
- [ ] Fills are reported accurately
- [ ] No unexpected errors

---

## Rollback Procedure

If issues occur:

### Immediate Stop

```bash
# Kill the process
Ctrl+C

# Or switch venue back to paper via API
curl -X POST http://127.0.0.1:8000/api/v1/pipeline/venue/mode \
  -H "Content-Type: application/json" \
  -d '{"venue": "alpaca", "mode": "paper"}'

# Or activate kill switch
curl -X POST http://127.0.0.1:8000/risk/kill-switch/enable
```

### Cancel Open Orders

Use the ExecutionGuard kill switch:

```python
from merid.execution_guard import ExecutionGuard
guard = ExecutionGuard()
guard.activate_kill_switch(reason="Operator intervention")
```

### Review Logs

Check logs for errors:
```bash
grep -i error logs/merid.log
grep -i circuit logs/merid.log  # Circuit breaker trips
```

---

## Post-Go-Live Monitoring

### Daily Checks

- [ ] Review P&L
- [ ] Check for circuit breaker trips
- [ ] Verify position accuracy
- [ ] Monitor latency metrics

### Gradual Limit Increases

After 1 week of stable operation:
```bash
export MERID_MAX_ORDER_SIZE_USD=100
export MERID_MAX_DAILY_LOSS_USD=250
```

After 1 month:
```bash
export MERID_MAX_ORDER_SIZE_USD=500
export MERID_MAX_DAILY_LOSS_USD=1000
```

---

## Quick Reference

| Command | Description |
|---------|-------------|
| `make preflight` | Tests + readiness + drift + RiskContext |
| `make golden-path` | 490-test golden path suite |
| `make risk-context` | Print live RiskContext JSON |
| `make loop-start` | Start MeridLoop (observe) |
| `make loop-start-execute` | Start MeridLoop with execution |

## Safety Reminders

1. **Start small** - Use conservative limits initially
2. **Monitor closely** - Watch first few trades
3. **Keep confirmation on** - Don't disable `MERID_REQUIRE_CONFIRMATION`
4. **Know how to stop** - Have rollback procedure ready
5. **Check circuit breakers** - Review `get_circuit_status()` regularly

---

## Hard Risk Switches

MERID includes hard safety controls that automatically halt trading when limits are breached.

### Kill Switch Types

| Switch | Trigger | Recovery |
|--------|---------|----------|
| **Global Kill** | Manual `emergency_stop()` | Manual `reset()` |
| **Daily Loss** | P&L < -`MERID_MAX_DAILY_LOSS_USD` | New trading day (UTC) |
| **Position Limit** | Total positions > limit | Manual `reset()` |
| **Error Threshold** | >10 errors/hour | Manual `reset()` |

### Using Kill Switches

```python
from merid.execution_guard import ExecutionGuard

guard = ExecutionGuard()

# Check before every trade (done automatically by MeridLoop)
result = guard.pre_trade_check(domain="crypto", notional_usd=100.0)
if not result.allowed:
    print(f"Blocked: {result.reason}")

# Emergency stop
guard.activate_kill_switch(reason="Operator intervention")

# Check status
print(guard.summary())

# Or via API:
# POST /risk/kill-switch/enable
# GET /api/v1/pipeline/risk-context
```

### Monitoring Kill Switches

Add to your monitoring dashboard:

```python
from merid.pipeline.risk_context import build_risk_context

def check_risk_health():
    ctx = build_risk_context()
    
    # Alert if scale factor is low (system under stress)
    if ctx.size_scale_factor < 0.5:
        alert(f"Scale factor low: {ctx.size_scale_factor:.2f}")
    
    # Alert if killed
    if ctx.kill_switch_active:
        alert("TRADING HALTED: Kill switch active")
```

### Kill Switch Callbacks

Register callbacks for alerts:

Kill switch events are logged to the OperatorSession and visible in the Operator Dashboard view.

Monitor via:
```bash
make risk-context    # CLI
curl http://127.0.0.1:8000/api/v1/pipeline/risk-context | jq  # API
```

### Integration with Resilience Layer

Kill switches integrate with circuit breakers:

The ExecutionGuard integrates with per-domain circuit breakers. When CQI drops
below threshold, the guard automatically throttles execution via `size_scale_factor`.

---

## Operator Notes

*Rough edges discovered during operator testing (2026-02-04):*

### Windows Users

**Issue**: `make` is not available on Windows by default.

**Workaround**: Run the Python commands directly:

```powershell
# Instead of: make golden-path
python -m pytest tests/test_e2e_golden_path.py tests/test_signal_layer.py tests/test_live_feeds.py tests/test_prediction_markets.py tests/test_unified_pipeline.py tests/test_canonical_agents.py tests/test_hardening.py -v

# Instead of: make serve
uvicorn web.main:app --host 0.0.0.0 --port 8000

# Instead of: make loop-start
python -m merid.loop

# Instead of: make risk-context
python -c "from merid.pipeline.risk_context import build_risk_context; import json; print(json.dumps(build_risk_context().__dict__, indent=2, default=str))"
```

**Alternative**: Install `make` via Chocolatey (`choco install make`) or use WSL.

### pytest Warnings

**Issue**: `PytestUnknownMarkWarning` for `@pytest.mark.smoke`

**Fix**: Register the mark in `pytest.ini` or `pyproject.toml`:
```ini
[pytest]
markers =
    smoke: marks tests as smoke tests
    e2e: marks tests as end-to-end tests
```

### Neo4j Deprecation Warning

**Issue**: `DeprecationWarning` about Neo4j driver session closing.

**Status**: Non-blocking. Will be fixed in a future Neo4j driver update. Can be suppressed with:
```python
import warnings
warnings.filterwarnings("ignore", category=DeprecationWarning, module="neo4j")
```

### Credential Validation

**Note**: `validate-config` will show errors for venues you don't plan to use. To validate only specific venues:

```bash
# Check specific venue status
curl http://127.0.0.1:8000/api/v1/pipeline/venues | jq '.[] | select(.name=="kalshi")'
```

### Circuit Breaker Inspection

To check circuit breaker status for a venue client:

```bash
# Check risk context (includes CQI, scale factor, domain exposure)
make risk-context

# Or via API
curl http://127.0.0.1:8000/api/v1/pipeline/risk-context | jq
```

### Dry-Run Flag

**Note**: The `--dry-run` flag for `run_paper_demo.py` is not yet implemented. Paper mode already simulates trades without real execution, so this is functionally equivalent.
