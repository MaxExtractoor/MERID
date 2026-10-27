# RB-4: Config Violation at Startup

**Alert:** `merid_startup_enforcement_checks_total{result="fail"} > 0` or application fails to start

## Symptoms

- Application aborts during startup
- Log: `RiskConfigViolationError: {violation details}`
- Log: `{"event_type": "STARTUP_ENFORCEMENT", "success": false}`
- Error message includes specific config value that violates policy
- Exit code non-zero

## Impact

- Application **cannot start**
- Trading system unavailable
- Existing positions not affected (system not running)
- Safe failure - prevents trading with unsafe config

## Common Violations

| Violation | Log Indicator | Fix |
|-----------|---------------|-----|
| Global cap > 2% | `max_risk_pct_global=0.06 exceeds maximum 0.02` | Reduce to ≤0.02 |
| Fixed USD in live | `Fixed USD sizing not allowed in live mode` | Remove fixed USD, use % |
| Max edges > 3 | `max_edges=5 exceeds maximum 3` | Reduce to ≤3 |
| Unsafe per-trade % | `max_risk_pct_per_trade=0.03 exceeds 0.01` | Reduce to ≤0.01 |

## Investigation

### Step 1: Identify Violating Config

```bash
# Check startup logs
grep "RiskConfigViolationError\|Risk config violation" /var/log/merid/startup.log

# Example output:
# RiskConfigViolationError: max_risk_pct_global=0.06 (6%) exceeds absolute maximum 0.02 (2%)
# RiskConfigViolationError: max_total_notional_usd=5000 not allowed in live mode
```

### Step 2: Locate Config Source

```bash
# Check which config files are being loaded
grep "Loading config\|portfolio_optimizer\|risk_config" /var/log/merid/startup.log

# Check environment variables
env | grep -i "MERID\|KALSHI" | grep -i "risk\|mode"
```

### Step 3: Check All Config Values

```bash
# Find all risk-related configs
grep -r "max_risk_pct_global\|max_total_notional" config/
grep -r "max_risk_pct_global\|max_total_notional" merid/config/

# Check for overrides
env | grep -i "risk\|cap\|limit"
```

## Remediation

### Case A: Global Risk Cap > 2%

**Error:** `max_risk_pct_global=0.06 exceeds maximum 0.02`

**Fix:**
```bash
# Edit config file
vim config/portfolio_optimizer.yaml

# Change:
# max_risk_pct_global: 0.06  # OLD - 6%
max_risk_pct_global: 0.02    # NEW - 2%

# Or for safer initial deployment:
max_risk_pct_global: 0.01    # 1% - more conservative
```

### Case B: Fixed USD Sizing in Live/Paper

**Error:** `Fixed USD sizing not allowed in live mode`

**Fix:**
```bash
# Edit config file
vim config/portfolio_optimizer.yaml

# Remove or comment out:
# max_total_notional_usd: 5000  # REMOVE THIS

# Ensure percentage-based sizing is configured:
max_risk_pct_per_trade: 0.01  # 1% per trade
```

### Case C: Too Many Edges

**Error:** `max_edges=5 exceeds maximum 3`

**Fix:**
```bash
vim config/batch_manager.yaml

# Change:
# max_edges: 5  # OLD
max_edges: 3     # NEW - maximum allowed
```

### Case D: Per-Trade Risk Too High

**Error:** `max_risk_pct_per_trade=0.03 exceeds 0.01`

**Fix:**
```bash
vim config/portfolio_optimizer.yaml

# Change:
# max_risk_pct_per_trade: 0.03  # OLD - 3%
max_risk_pct_per_trade: 0.01    # NEW - 1%
```

## Verification

### Before Restarting

```bash
# Test config validation manually
python -c "
from merid.config.unified_risk_enforcement import enforce_at_startup, RiskConfigViolationError
from unittest.mock import patch

with patch('merid.config.unified_risk_enforcement._get_current_trade_mode', return_value='live'):
    try:
        enforce_at_startup()
        print('✓ Config validation passed')
    except RiskConfigViolationError as e:
        print(f'✗ Config validation failed: {e}')
"

# Expected: ✓ Config validation passed
```

### After Restart

```bash
# Start application
python -m web.main

# Check startup logs
tail -f /var/log/merid/startup.log | grep -E "STARTUP_ENFORCEMENT|Risk|Unified"

# Expected lines:
# "Phase -1c: Unified Risk Model Enforcement"
# "✓ Risk model validated"
# "STARTUP_ENFORCEMENT": {"success": true}

# Verify no CRITICAL errors
grep "CRITICAL\|RiskConfigViolationError" /var/log/merid/startup.log
# Expected: No matches
```

### Full System Verification

```bash
# Health check
curl http://localhost:8000/api/v1/health | jq
# Expected: {"status": "ok", ...}

# Check risk config endpoint
curl http://localhost:8000/api/v1/risk/config | jq
# Expected: max_risk_pct_global <= 0.02

# Check metrics
curl http://localhost:9100/metrics | grep merid_startup_enforcement_checks_total
# Expected: {result="pass"} > 0
```

## Prevention

### Pre-Deployment Validation

Add to CI/CD pipeline:

```bash
# Validate config before deployment
python -c "
from merid.config.unified_risk_enforcement import enforce_at_startup
from unittest.mock import patch

with patch('merid.config.unified_risk_enforcement._get_current_trade_mode', return_value='live'):
    enforce_at_startup()
    print('Config validation passed')
"

# Only deploy if validation passes
```

### Config Templates

Provide safe default configs:

```yaml
# config/safe_defaults.yaml
max_risk_pct_global: 0.02      # 2% absolute maximum
max_risk_pct_per_trade: 0.01   # 1% per trade
max_edges: 3                   # Max 3 concurrent edges
# NO fixed USD sizing in production
```

### Monitoring

```yaml
# Alert if config validation fails
- alert: ConfigValidationFailed
  expr: merid_startup_enforcement_checks_total{result="fail"} > 0
  labels:
    severity: critical
  annotations:
    summary: "Config violation prevented startup"
```

## Escalation

**Contact:** #platform-engineering if:
- Config appears correct but still fails validation
- Unclear which config source is causing violation
- Need to temporarily override for emergency fix

**Note:** Do not bypass validation without executive approval - this is a critical safety control.

## Related

- Enforcement location: `merid/config/unified_risk_enforcement.py`
- Wiring: `web/main.py` (Phase -1c)
- Test: `tests/risk/test_unified_risk_enforcement.py`
- CI Invariant: `check_startup_enforcement()`
