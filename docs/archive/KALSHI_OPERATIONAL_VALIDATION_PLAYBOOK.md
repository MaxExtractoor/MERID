# Kalshi Operational Validation Playbook

**Purpose**: Verify that the runtime execution follows the documented ownership matrix and architectural boundaries defined in `KALSHI_MODULE_OWNERSHIP_MATRIX.md`.

**Scope**: Production validation of end-to-end alignment, not structural fixes.

---

## Validation Infrastructure

The stack already has trace correlation infrastructure in place:

- `decision_trace.py`: `new_decision_trace_id()` generates opaque trace IDs
- `order_router.py`: `OrderIntent.decision_trace_id` carries trace through routing
- `fills_ledger.py`: `KalshiFill.decision_trace_id` links fills to decisions
- `agent_grid_15m.py`: `[TRADE-TRACE]` logs with `decision_stage` and `decision_reason`

This enables end-to-end correlation: decision → routing → fill → settlement.

---

## Validation 1: Decision Trace to Fill Correlation

**Objective**: Compare expected edge at decision time to realized PnL at settlement.

**Query Pattern**:
```sql
-- Join fills to decision traces
SELECT 
    kf.decision_trace_id,
    kf.market_ticker,
    kf.side,
    kf.price_cents as fill_price_cents,
    kf.count_fp as fill_contracts,
    kf.settlement_pnl_cents,
    kf.settlement_outcome,
    -- Extract decision context from logs (parse TRADE-TRACE)
    -- Expected edge, spread, model_prob from decision time
FROM kalshi_fills kf
WHERE kf.decision_trace_id IS NOT NULL
  AND kf.settlement_outcome IS NOT NULL
ORDER BY kf.ingested_at DESC
LIMIT 100;
```

**Validation Checks**:
- [ ] `decision_trace_id` is present on fills for agent-generated trades
- [ ] Expected edge (from TRADE-TRACE) vs realized PnL shows positive correlation
- [ ] Outliers (>2σ deviation) are investigated for drift causes
- [ ] Fee-aware vs fee-agnostic edge calculations are not mixed in same trace

**Log Parse Pattern**:
```python
# Extract decision context from TRADE-TRACE log
# Example log line:
# [TRADE-TRACE] trace_id=ta-abc123 | ... | edge_actual=0.05 | spread_cents=2 | ...

import re
pattern = r"edge_actual=([\d.]+)|spread_cents=(\d+)|decision_stage=(\w+)|decision_reason=(\w+)"
```

---

## Validation 2: Rejection Reason Code Consistency

**Objective**: Verify rejected trades match documented reason codes.

**Documented Reason Codes** (from `agent_grid_15m.py`):
- `PRE_TRADE_VALIDATION`: Price invalid, bankroll insufficient, etc.
- `NO_EDGE_NO`: Edge below threshold
- `WINDOW_INVALID`: Outside entry window
- `LIQUIDITY_INVALID`: Book illiquid or executable=False

**Query Pattern**:
```sql
-- Count rejections by reason code
SELECT 
    decision_reason,
    decision_stage,
    COUNT(*) as rejection_count
FROM (
    -- Parse TRADE-TRACE logs to extract decision_stage and decision_reason
    -- This requires log aggregation (e.g., ELK, Loki)
) parsed_logs
WHERE decision = 'REJECT'
GROUP BY decision_reason, decision_stage
ORDER BY rejection_count DESC;
```

**Validation Checks**:
- [ ] All rejections have valid `decision_stage` and `decision_reason`
- [ ] No unknown reason codes appear
- [ ] Rejection distribution matches expected patterns (e.g., NO_EDGE_NO most common)
- [ ] Fallback rejection paths (error handling branches) are documented

**Runtime Guard**:
```python
# Add to agent_grid_15m.py for production safety
VALID_DECISION_STAGES = {
    "PRE_TRADE_VALIDATION",
    "NO_EDGE_NO",
    "WINDOW_INVALID",
    "LIQUIDITY_INVALID",
    "SUBMIT_ORDER_INTENT",
}

VALID_DECISION_REASONS = {
    "INVALID_PRICE",
    "INSUFFICIENT_BANKROLL",
    "EDGE_BELOW_THRESHOLD",
    "OUTSIDE_ENTRY_WINDOW",
    "BOOK_ILLIQUID",
    "POSITION_LIMIT_EXCEEDED",
}

def log_trade_trace(..., decision_stage, decision_reason):
    if decision_stage not in VALID_DECISION_STAGES:
        logger.error(f"[TRACE-GUARD] Invalid decision_stage: {decision_stage}")
    if decision_reason not in VALID_DECISION_REASONS:
        logger.error(f"[TRACE-GUARD] Invalid decision_reason: {decision_reason}")
    # ... existing log logic
```

---

## Validation 3: Fee Calculation Path Consistency

**Objective**: Confirm fee-aware and fee-agnostic calculations are never mixed in the same decision path.

**Fee Calculation Locations**:
- `kalshi_risk.py`: Canonical fee model (trading + settlement fees)
- `unified_sizing.py`: Fee adjustment on max_notional (consider_fee_impact)
- `order_router.py`: Estimated fee in OrderIntent (estimated_fee_cents)
- `edge_model.py`: Fee-aware EV (separate from edge threshold)

**Validation Checks**:
- [ ] `get_effective_edge_threshold` is NEVER called with fee-adjusted spread
- [ ] `consider_fee_impact=True` in sizing is matched by `estimated_fee_cents` in OrderIntent
- [ ] Fee-aware EV calculations in `edge_model.py` are clearly labeled and not used for edge threshold
- [ ] Post-fee edge in fills_ledger matches pre-fee edge minus estimated fees

**Log Correlation**:
```python
# In agent_grid_15m.py, log fee-awareness explicitly
logger.info(
    "[TRADE-TRACE] ... | edge_actual=%.4f | edge_fee_aware=%s | estimated_fee_cents=%d",
    edge_actual,
    "yes" if consider_fee_impact else "no",
    estimated_fee_cents or 0
)
```

---

## Validation 4: Venue Position Limit Approximation

**Objective**: Verify internal position limit approximations do not cause hidden over-sizing.

**Current Implementation**:
- `kalshi_risk.py`: `max_position_per_contract = 500` (internal approximation)
- TODO comment added: Query actual limits from Kalshi API

**Validation Checks**:
- [ ] Order rejections with "POSITION_LIMIT" error from Kalshi API are monitored
- [ ] If POSITION_LIMIT rejections occur, internal cap is too high
- [ ] Internal cap is conservative (lower than actual venue limits)
- [ ] Per-asset caps from profile are also conservative

**Monitoring Query**:
```sql
-- Track position limit rejections from venue
SELECT 
    market_ticker,
    COUNT(*) as position_limit_rejections
FROM kalshi_fills kf
WHERE kf.raw_payload LIKE '%position limit%'
  OR kf.raw_payload LIKE '%POSITION_LIMIT%'
GROUP BY market_ticker;
```

**Action Threshold**:
- If >1% of orders hit venue POSITION_LIMIT, reduce internal cap by 20%

---

## Validation 5: Magic Number Runtime Guard

**Objective**: Detect new magic numbers added outside centralized invariants.

**Static Analysis** (pre-commit):
```bash
# Add to pre-commit hooks
# Scan for probability clamps outside invariants.py
grep -r "max(0\.02" --include="*.py" merid/ | grep -v "invariants.py" | grep -v "test"
grep -r "min(0\.98" --include="*.py" merid/ | grep -v "invariants.py" | grep -v "test"

# Scan for edge thresholds outside invariants.py
grep -r "min_edge" --include="*.py" merid/ | grep -v "invariants.py" | grep -v "config" | grep -v "test"
```

**Runtime Guard** (startup validation):
```python
# Add to startup_validations.py
def check_no_stray_probability_clamps():
    """Warn if probability clamps exist outside invariants.py."""
    import subprocess
    result = subprocess.run(
        ["grep", "-r", "max(0\\.02", "--include=*.py", "merid/"],
        capture_output=True,
        text=True
    )
    violations = [line for line in result.stdout.split('\n') 
                  if line and "invariants.py" not in line and "test" not in line]
    if violations:
        logger.warning(
            f"[MAGIC-NUMBER-GUARD] Found {len(violations)} probability clamps outside invariants.py"
        )
```

---

## Continuous Monitoring Setup

### Log Aggregation Rules

**Loki/Promtail**:
```yaml
# Extract TRADE-TRACE fields
- source_labels:
    - __journal__systemd_unit
  regex: 'TRADE-TRACE.*trace_id=([^|]+)'
  target_label: trace_id
- source_labels:
    - __journal__systemd_unit
  regex: 'decision_stage=([^|]+)'
  target_label: decision_stage
- source_labels:
    - __journal__systemd_unit
  regex: 'decision_reason=([^|]+)'
  target_label: decision_reason
```

### Grafana Dashboards

**Panel 1: Decision Trace Correlation**
- Query: Count fills with decision_trace_id vs without
- Alert: <90% correlation

**Panel 2: Rejection Reason Distribution**
- Query: Count by decision_reason
- Alert: Unknown reason code appears

**Panel 3: Edge Drift**
- Query: Expected edge vs realized PnL scatter plot
- Alert: Correlation <0.5

**Panel 4: Position Limit Rejections**
- Query: Venue POSITION_LIMIT error count
- Alert: >1% of orders

---

## Validation Runbook

### Daily Checks
1. Run decision trace correlation query
2. Check rejection reason distribution
3. Verify no unknown reason codes
4. Review edge drift outliers

### Weekly Checks
1. Run static analysis for magic numbers
2. Review position limit rejection rate
3. Validate fee calculation path consistency
4. Check for new fallback branches

### Monthly Checks
1. Full end-to-end trace audit (sample 100 trades)
2. Compare internal caps to venue limits
3. Review and update VALID_DECISION_STAGES/REASONS
4. Update ownership matrix if architecture changes

---

## Incident Response

### If Drift Detected

**Step 1: Isolate the drift**
- Identify which module is violating ownership matrix
- Check if it's a new fallback branch or existing code path

**Step 2: Determine severity**
- HIGH: Affects economics (PnL, edge, fees)
- MEDIUM: Affects logging/traceability
- LOW: Affects non-critical paths

**Step 3: Remediate**
- If HIGH: Hotfix to delegate to canonical helper
- If MEDIUM: Add warning and plan fix
- If LOW: Document as intentional divergence

**Step 4: Update guardrails**
- Add lint rule to prevent recurrence
- Add runtime guard if appropriate
- Update ownership matrix if change is intentional

---

## Success Criteria

The operational validation is successful when:

- [ ] >95% of fills have decision_trace_id correlation
- [ ] All rejection reasons are documented and consistent
- [ ] Fee-aware and fee-agnostic paths are never mixed
- [ ] Position limit rejections from venue are <0.1% of orders
- [ ] No new magic numbers appear outside invariants.py
- [ ] Edge drift (expected vs realized) correlation >0.7
- [ ] All validation checks pass in daily/weekly/monthly runbook

---

## Next Steps

1. Implement runtime guard for decision reason codes
2. Set up log aggregation for TRADE-TRACE parsing
3. Create Grafana dashboard for monitoring
4. Add pre-commit hook for magic number detection
5. Schedule first full end-to-end trace audit
