# Next Steps: Trading Gate Validation Execution

> **Status**: Implementation complete, ready for PR review and staging validation
> **Created**: 2026-04-02
> **Branch**: claude/run-trading-gate-validation

This document outlines the concrete steps to execute after merging the validation tooling PR.

---

## Step 1: Open PR and Add Summary

### PR Title
```
Add staging validation runbook and CI guardrails for trading gates
```

### PR Description

Use this as the PR description:

```markdown
## Summary

This PR adds comprehensive documentation and CI guardrails for validating MERID's full trading mode with 10-minute and 30-minute performance gates.

**Key constraint**: CI cannot run sustained 10-30 minute full-stack gates due to ephemeral runners, resource constraints, and duration requirements. This PR provides the tooling and documentation for proper validation in staging environments.

## What's Included

### 📖 Documentation (857 new lines)

- **`docs/STAGING_FULL_TRADING_VALIDATION_RUNBOOK.md`** (452 lines)
  - Complete step-by-step procedures for staging validation
  - Environment setup (VALIDATION_MODE=0, full stack requirements)
  - Exact commands for 5-min smoke test, 10-min gate, 30-min gate
  - Official go/no-go criteria: P95<500ms, P99<800ms, Max<1000ms, degraded=0, failed_polls=0
  - Troubleshooting guide and monitoring setup

- **`docs/PRE_LIVE_CHECKLIST.md`** (Section 4A added)
  - New staging validation requirements
  - Links to runbook for detailed procedures
  - Clear go/no-go decision rule: "If ANY criterion fails, DO NOT go live"

### 🔧 CI Guardrails

- **`.github/workflows/validate-gate-tooling.yml`** (207 lines)
  - Static validation that tooling remains functional
  - Verifies scripts exist and can show help
  - Checks documentation structure and consistency
  - **Does NOT run actual 10-30 minute gates** (those run in staging)

### 📋 Reference Documentation

- **`PR_SUMMARY_GATE_VALIDATION_TOOLING.md`**
  - Complete implementation justification
  - Explains CI constraint in detail
  - Usage guide for operators and engineers

## Why This Approach

| Task | Environment | Rationale |
|------|-------------|-----------|
| Unit/integration tests | CI | Fast, isolated, deterministic |
| **10-30 min sustained gates** | **Staging** | Production-like infra, realistic load |
| Tooling validation | CI | Ensure scripts remain functional |

Attempting performance gates in CI would produce unreliable baselines and waste resources.

## Testing

All verification checks passed:
- ✅ Scripts functional (`--help`, `--dry-run` work)
- ✅ Documentation complete with required sections
- ✅ Thresholds consistent across all docs (P95<500ms, P99<800ms, Max<1000ms)
- ✅ Checklist properly updated with Section 4A

## Next Steps After Merge

1. **In staging**: Follow [STAGING_FULL_TRADING_VALIDATION_RUNBOOK.md](docs/STAGING_FULL_TRADING_VALIDATION_RUNBOOK.md)
2. **Run gates**: 10-minute validation, then 30-minute go-live gate
3. **Update checklist**: Mark Section 4A items as ✅ with archived results
4. **Before live**: Get stakeholder sign-offs per PRE_LIVE_CHECKLIST.md

## Files Changed

**Created:**
- `docs/STAGING_FULL_TRADING_VALIDATION_RUNBOOK.md`
- `.github/workflows/validate-gate-tooling.yml`
- `PR_SUMMARY_GATE_VALIDATION_TOOLING.md`

**Modified:**
- `docs/PRE_LIVE_CHECKLIST.md` (added Section 4A)

## Related Documentation

- [VALIDATION_GUIDE.md](VALIDATION_GUIDE.md) - Event loop monitoring technical details
- [FULL_TRADING_MODE_GATE_VALIDATION.md](docs/FULL_TRADING_MODE_GATE_VALIDATION.md) - Optimization context
- Existing validation scripts: `scripts/run_trading_gate.py`, `scripts/analyze_gate_results.py`
```

### Link to Key Files

In the PR description or as a comment, explicitly link to:
- 📖 [STAGING_FULL_TRADING_VALIDATION_RUNBOOK.md](docs/STAGING_FULL_TRADING_VALIDATION_RUNBOOK.md)
- ✅ [PRE_LIVE_CHECKLIST.md Section 4A](docs/PRE_LIVE_CHECKLIST.md#section-4a--staging-full-trading-mode-validation)

---

## Step 2: Merge and Tag

### After PR Approval

1. **Merge to main**:
   ```bash
   # Assuming PR is approved and checks pass
   git checkout main
   git pull origin main
   git merge --no-ff claude/run-trading-gate-validation
   git push origin main
   ```

2. **Create milestone tag**:
   ```bash
   # Tag this as a milestone for validation tooling
   git tag -a trading-gate-validation-tooling -m "Trading gate validation tooling and documentation complete

   This tag marks the completion of:
   - Staging validation runbook (STAGING_FULL_TRADING_VALIDATION_RUNBOOK.md)
   - Pre-live checklist updates (Section 4A)
   - CI guardrails for gate tooling validation

   Next step: Run actual 10-min and 30-min gates in staging per runbook."

   git push origin trading-gate-validation-tooling
   ```

3. **Verify tag**:
   ```bash
   git tag -l trading-gate-validation-tooling -n5
   ```

---

## Step 3: Schedule Staging Run

### Environment Preparation

On your staging server (production-like infrastructure):

```bash
# 1. Ensure environment variables are set
export VALIDATION_MODE=0              # Full trading mode (not validation-light)
export MERID_TRADE_MODE=paper         # Still paper mode
export MERID_ALLOW_LIVE_TRADES=false  # Live trades still disabled

# 2. Verify environment
echo "Validation mode: $VALIDATION_MODE"
echo "Trade mode: $MERID_TRADE_MODE"
echo "Live trades: $MERID_ALLOW_LIVE_TRADES"

# 3. Pull latest code
cd /path/to/MERID
git fetch origin
git checkout trading-gate-validation-tooling  # Use the tagged version
git pull

# 4. Start MERID with full stack
python -m web.main
```

### Pre-Flight Checks

Before running gates, verify system health:

```bash
# Health check
curl -s http://localhost:8000/api/health | jq '{status, degraded}'
# Expected: {"status": "healthy", "degraded": false}

# Event loop monitor check
curl -s http://localhost:8000/health/event_loop | jq '{running, degraded, p95_ms: .stats_1m.p95_ms}'
# Expected: {"running": true, "degraded": false, "p95_ms": <100}

# Check logs for full stack startup
tail -f logs/merid.log | grep -E "(Event Loop Monitor|MeridLoop|KalshiWebSocketBridge)"
```

**If any pre-flight check fails, stop and investigate before proceeding.**

### Run the Gates

Follow `docs/STAGING_FULL_TRADING_VALIDATION_RUNBOOK.md` exactly:

```bash
# Create reports directory
mkdir -p reports

# Optional: 5-minute smoke test
python scripts/run_trading_gate.py \
  --duration 5 \
  --output reports/smoke_test_$(date +%Y%m%d_%H%M%S).json

# Required: 10-minute validation gate
python scripts/run_trading_gate.py \
  --duration 10 \
  --output reports/gate_10min_$(date +%Y%m%d_%H%M%S).json

# Required: 30-minute go-live gate
python scripts/run_trading_gate.py \
  --duration 30 \
  --output reports/gate_30min_$(date +%Y%m%d_%H%M%S).json
```

### Analyze and Archive Results

```bash
# Analyze 10-minute gate
python scripts/analyze_gate_results.py \
  reports/gate_10min_*.json \
  --highlight-5min \
  > reports/gate_10min_analysis.txt

# Analyze 30-minute gate
python scripts/analyze_gate_results.py \
  reports/gate_30min_*.json \
  --highlight-5min \
  > reports/gate_30min_analysis.txt

# Archive passing results
cp reports/gate_10min_*.json reports/LIVE_READY_gate_10min_$(date +%Y%m%d).json
cp reports/gate_30min_*.json reports/LIVE_READY_gate_30min_$(date +%Y%m%d).json
cp reports/gate_*_analysis.txt reports/

# Commit to repository
git add reports/LIVE_READY_*
git commit -m "validation: 10-min and 30-min gates passed, system certified live-ready

Gate results:
- 10-min gate: P95=XXXms, P99=XXXms, degraded=0
- 30-min gate: P95=XXXms, P99=XXXms, degraded=0

All 5 go/no-go criteria met:
✅ P95 < 500ms
✅ P99 < 800ms
✅ Max < 1000ms
✅ degraded_samples = 0
✅ failed_polls = 0

System certified ready for initial live trading with conservative limits."

git push origin main
```

---

## Step 4: Record Results in PRE_LIVE_CHECKLIST

Update `docs/PRE_LIVE_CHECKLIST.md` Section 4A:

```bash
# Edit the checklist
vim docs/PRE_LIVE_CHECKLIST.md
```

Mark items as complete:

```markdown
## Section 4A — Staging Full Trading Mode Validation

| # | Check | How to verify | Status |
|---|-------|--------------|--------|
| 4A.1 | **10-minute gate passed in staging** | Run `python scripts/run_trading_gate.py --duration 10` and analyze results with `--highlight-5min` | ✅ |
| 4A.2 | 10-minute gate shows P95 < 500ms for all samples including T+5min windows | Check analyzer output: all samples show ✅ | ✅ |
| 4A.3 | **30-minute gate passed in staging** | Run `python scripts/run_trading_gate.py --duration 30` and analyze results | ✅ |
| 4A.4 | 30-minute gate meets all 5 go/no-go criteria | P95<500ms, P99<800ms, Max<1000ms, degraded=0, failed_polls=0 | ✅ |
| 4A.5 | Gate results archived with analyzer output | See `reports/LIVE_READY_gate_30min_YYYYMMDD.json` | ✅ |
```

Add notes documenting the results:

```markdown
**Gate Validation Results** (completed YYYY-MM-DD):
- **10-minute gate**: P95=XXX.Xms, P99=XXX.Xms, Max=XXX.Xms, degraded_samples=0
- **30-minute gate**: P95=XXX.Xms, P99=XXX.Xms, Max=XXX.Xms, degraded_samples=0
- **Artifacts**: `reports/LIVE_READY_gate_30min_YYYYMMDD.json`, analysis in `reports/gate_30min_analysis.txt`
- **Staging environment**: [describe: CPU cores, RAM, network latency to Kalshi]
- **Full stack confirmed**: 35 agents, 11 pipelines, WebSocket bridge active
```

Commit the update:

```bash
git add docs/PRE_LIVE_CHECKLIST.md
git commit -m "docs: Mark Section 4A complete - staging gates passed"
git push origin main
```

---

## Step 5: Enable Small-Size Live Trading

**ONLY proceed if ALL criteria in Section 4A are ✅.**

### Pre-Live Verification

Before flipping to live:

1. **Complete PRE_LIVE_CHECKLIST.md**: Ensure ALL sections (1-8) show ✅
2. **Get stakeholder sign-offs**: SRE Lead, Trading Lead, Engineering Lead, Risk Manager
3. **Review artifacts**: Confirm gate results are archived and accessible

### Configure Initial Conservative Limits

Edit risk configuration for initial live trading:

```python
# merid/event_venues/kalshi/crypto_kalshi_risk.py (or equivalent)

# INITIAL LIVE LIMITS (Week 1)
INITIAL_LIVE_CONFIG = {
    "enabled_assets": ["BTC"],  # Start with 1 asset only
    "enabled_timeframes": ["daily"],  # Start with 1 timeframe only
    "per_contract_size_cap": 10,  # $10 per contract (10% of normal $100)
    "per_minute_notional_cap": 50,  # $50 across all markets
    "max_concurrent_orders": 2,  # Very conservative
}

# Kill-switch config (tighter than validation thresholds)
LIVE_KILL_SWITCH_CONFIG = {
    "p95_threshold_ms": 400,  # Trigger at 400ms (validation was 500ms)
    "degraded_timeout_s": 180,  # Kill-switch after 3 min degraded
    "auto_fallback_to_paper": True,
}
```

### Set Up Monitoring Alerts

Configure runtime alerts (use your monitoring system):

```python
# Alert configuration
LIVE_ALERTS = {
    "event_loop_p95_high": {
        "threshold": 400,  # ms
        "duration": "5m",  # sustained for 5 minutes
        "severity": "HIGH",
        "action": "notify_on_call",
    },
    "event_loop_degraded": {
        "threshold": 1,  # any degraded=true
        "duration": "3m",
        "severity": "CRITICAL",
        "action": "trigger_kill_switch + notify_on_call",
    },
    "no_fills_timeout": {
        "threshold": 3600,  # 1 hour with no fills
        "severity": "MEDIUM",
        "action": "notify_trading_lead",
    },
}
```

### Flip to Live Trading

```bash
# 1. Set environment variables for live mode
export MERID_TRADE_MODE=live
export MERID_ALLOW_LIVE_TRADES=true
export MERID_LIVE_RISK_PROFILE=initial  # Use conservative initial config

# 2. Restart MERID
# ... (use your deployment process)

# 3. Verify live mode is active
curl -s http://localhost:8000/api/health | jq '{trade_mode, live_trades_allowed}'
# Expected: {"trade_mode": "live", "live_trades_allowed": true}

# 4. Monitor event loop continuously
watch -n 10 'curl -s http://localhost:8000/health/event_loop | jq ".stats_1m"'
```

### First Live Session Monitoring (Critical!)

**During the first live trading session**:

1. **Watch event loop P95** every 1-2 minutes for the first hour
2. **Monitor fills ledger**: Verify orders are being placed and filled correctly
3. **Check reconciliation**: No discrepancies between internal state and exchange
4. **Alert escalation**: Be ready to trigger kill-switch manually if needed

```bash
# Continuous monitoring commands
watch -n 30 'curl -s http://localhost:8000/health/event_loop | jq "{p95: .stats_1m.p95_ms, p99: .stats_1m.p99_ms, degraded}"'

# Check recent fills
curl -s http://localhost:8000/api/v1/fills/recent | jq '.fills[:5]'

# Check reconciliation status
curl -s http://localhost:8000/api/v1/reconciliation/status | jq .
```

### Gradual Expansion Plan

After **1 week stable** at initial limits (no incidents, P95 < 400ms sustained):

```python
# Week 2 config
WEEK_2_CONFIG = {
    "enabled_assets": ["BTC", "ETH"],  # Add 1 more asset
    "per_contract_size_cap": 25,  # Increase to 25% of normal
    "per_minute_notional_cap": 100,
}
```

After **2 weeks total**:

```python
# Week 3+ config
WEEK_3_CONFIG = {
    "enabled_assets": ["BTC", "ETH", "SOL"],
    "enabled_timeframes": ["daily", "1h"],  # Add 1h timeframe
    "per_contract_size_cap": 50,  # 50% of normal
    "per_minute_notional_cap": 250,
}
```

After **1 month total** (if no incidents):

```python
# Full production config
FULL_PROD_CONFIG = {
    "enabled_assets": ["BTC", "ETH", "SOL", "XRP", "DOGE"],  # All assets
    "enabled_timeframes": ["15m", "1h", "daily", "weekly", "monthly"],  # All timeframes
    "per_contract_size_cap": 100,  # Full normal size
    "per_minute_notional_cap": 1000,
}
```

**Important**: Only expand if:
- ✅ No kill-switch triggers in previous period
- ✅ P95 lag < 400ms sustained
- ✅ No reconciliation discrepancies
- ✅ Fill rate meets expectations

---

## Rollback Plan

If any issues occur during live trading:

### Immediate Rollback (Emergency)

```bash
# 1. Trigger kill-switch via API
curl -X POST http://localhost:8000/api/kill_switch/activate \
  -H "Content-Type: application/json" \
  -d '{"reason": "Emergency rollback - event loop degraded"}'

# 2. Verify kill-switch active
curl -s http://localhost:8000/api/kill_switch | jq '{active, reason}'

# 3. Set environment back to paper
export MERID_TRADE_MODE=paper
export MERID_ALLOW_LIVE_TRADES=false

# 4. Restart MERID
# ... (use your deployment process)
```

### Investigate and Fix

1. Capture profiling data: `curl http://localhost:8000/health/event_loop/profiles/summary`
2. Review logs for errors/warnings
3. Compare metrics to gate baseline
4. Fix root cause
5. Re-run 30-minute gate in staging to verify fix
6. Only re-enable live after passing validation again

---

## Summary Checklist

Use this as your execution checklist:

```
□ Step 1: Open PR with summary
  □ Add PR description (use template above)
  □ Link to runbook and checklist Section 4A
  □ Wait for reviews and CI checks

□ Step 2: Merge and tag
  □ Merge PR to main
  □ Create tag: trading-gate-validation-tooling
  □ Push tag to origin

□ Step 3: Run staging gates
  □ Set up staging environment (VALIDATION_MODE=0)
  □ Run pre-flight checks
  □ Run 10-minute gate
  □ Run 30-minute gate
  □ Analyze results with --highlight-5min
  □ Archive passing results to reports/LIVE_READY_*
  □ Commit and push artifacts

□ Step 4: Update checklist
  □ Mark Section 4A items as ✅
  □ Add gate results summary
  □ Document staging environment specs
  □ Commit and push

□ Step 5: Enable live trading (only if all ✅)
  □ Complete ALL PRE_LIVE_CHECKLIST sections
  □ Get stakeholder sign-offs
  □ Configure initial conservative limits
  □ Set up monitoring alerts
  □ Flip environment to live mode
  □ Monitor first session closely
  □ Follow gradual expansion plan
```

---

## Contact and Escalation

If issues arise during any step:

- **Event loop degraded**: Immediately trigger kill-switch, rollback to paper
- **Gate failures**: Do not proceed to live, investigate and re-run gates
- **Reconciliation errors**: Halt trading, review ledger inconsistencies
- **Unexpected behavior**: Pause, capture logs/metrics, consult team

**Do not proceed to the next step if the current step has any failures or uncertainties.**

---

**End of Next Steps Guide**
