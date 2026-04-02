# PR Summary: Trading Gate Validation Tooling and Documentation

## Context and Constraint

The MERID system has completed event-loop optimizations and now requires validation via 10-minute and 30-minute full-stack trading gates before enabling live trading. However, **CI cannot run sustained 10-30 minute gates** due to:

1. **Environment constraints**: CI runners are ephemeral with limited resources and timeouts
2. **Infrastructure requirements**: Gates require full MERID stack with VALIDATION_MODE=0, all agents active, WebSocket connections, database, and production-like infrastructure
3. **Duration requirements**: 10-30 minutes of sustained operation under realistic load
4. **Meaningful validation**: Performance metrics are only meaningful in a staging/pre-production environment that mirrors production

**This PR does NOT attempt to run gates in CI.** Instead, it provides the tooling, documentation, and CI guardrails to ensure validation can be properly executed in staging.

---

## Implementation

This PR delivers:

### 1. Staging Validation Runbook
**File**: `docs/STAGING_FULL_TRADING_VALIDATION_RUNBOOK.md`

A comprehensive, step-by-step runbook for running gate validation in staging:
- **Environment setup**: Exact configuration requirements (VALIDATION_MODE=0, full stack)
- **Pre-flight checks**: Health endpoint verification before starting gates
- **Step 1**: 5-minute smoke test (optional but recommended)
- **Step 2**: 10-minute validation gate with T+5min window analysis
- **Step 3**: 30-minute go-live gate with 5 official go/no-go criteria
- **Exact commands**: Copy-paste ready commands for all steps
- **Go/No-Go thresholds**: Clear criteria (P95<500ms, P99<800ms, Max<1000ms, degraded=0, failed_polls=0)
- **Result archival**: How to capture and store passing gate evidence
- **Troubleshooting**: Common issues and fixes
- **Monitoring guidance**: Runtime alerts and initial live limits

### 2. Pre-Live Checklist Update
**File**: `docs/PRE_LIVE_CHECKLIST.md`

Added **Section 4A — Staging Full Trading Mode Validation** with:
- 5 specific validation requirements (10-min gate, 30-min gate, criteria verification)
- Explicit link to staging runbook for procedures
- Clear go/no-go decision rule: "If ANY criterion fails, DO NOT go live"
- Status checkboxes for tracking validation completion

### 3. CI Validation Workflow
**File**: `.github/workflows/validate-gate-tooling.yml`

A lightweight CI workflow that validates tooling and documentation **without running actual gates**:

**What it checks (static validation only):**
- ✅ Gate scripts exist (`run_trading_gate.py`, `run_paper_gate.py`, `analyze_gate_results.py`)
- ✅ Scripts can show `--help` without errors
- ✅ Scripts can run `--dry-run` (import validation)
- ✅ Scripts can be imported programmatically (for library use)
- ✅ Documentation files exist and have required sections
- ✅ Runbook mentions CI constraint and staging requirement
- ✅ Go/no-go thresholds are consistent across documentation
- ✅ PRE_LIVE_CHECKLIST links to staging runbook

**What it does NOT do:**
- ❌ Does not run 10-30 minute gates (impossible in CI)
- ❌ Does not start MERID server or full stack
- ❌ Does not measure actual performance
- ❌ Does not attempt to validate against production-like load

**Purpose**: Enforce that the tooling and documentation for live-ready validation are present, correct, and importable. The actual execution happens in staging per the runbook.

---

## Why This Approach

### The Right Tool for the Right Environment

| Task | Environment | Why |
|------|-------------|-----|
| **Unit tests** | CI | Fast, isolated, deterministic |
| **Integration tests** | CI | Controlled environment, known dependencies |
| **10-30 min sustained gates** | Staging | Production-like infra, realistic load, meaningful metrics |
| **Tooling validation** | CI | Ensure scripts and docs are correct |

Attempting to run sustained performance gates in CI would produce:
- False negatives (CI resource constraints don't reflect production)
- False positives (CI might pass but staging fails)
- Wasted CI resources (long-running jobs blocking other builds)
- Unreliable baselines (CI performance varies between runs)

### What This PR Achieves

1. **Explicit constraint documentation**: Makes clear that gates run in staging, not CI
2. **Executable procedures**: Engineers can follow the runbook step-by-step
3. **Automated guardrails**: CI ensures tooling stays functional as code evolves
4. **Audit trail**: PRE_LIVE_CHECKLIST tracks validation completion
5. **Consistent thresholds**: All docs agree on the same go/no-go criteria

---

## Usage

### For SRE/Operators (Staging Validation)

```bash
# 1. Set up staging environment
export VALIDATION_MODE=0
export MERID_TRADE_MODE=paper
export MERID_ALLOW_LIVE_TRADES=false

# 2. Start MERID with full stack
python -m web.main

# 3. Follow the runbook
cat docs/STAGING_FULL_TRADING_VALIDATION_RUNBOOK.md

# 4. Run gates
python scripts/run_trading_gate.py --duration 10
python scripts/run_trading_gate.py --duration 30

# 5. Check PRE_LIVE_CHECKLIST and mark Section 4A as complete
```

### For Engineers (CI Guardrails)

The CI workflow runs automatically on PR/push when gate scripts or docs change. It ensures:
- Scripts remain importable and functional
- Documentation stays in sync
- No accidental removal of critical files

---

## Files Changed

### Created
- ✅ `docs/STAGING_FULL_TRADING_VALIDATION_RUNBOOK.md` (425 lines)
- ✅ `.github/workflows/validate-gate-tooling.yml` (186 lines)

### Modified
- ✅ `docs/PRE_LIVE_CHECKLIST.md` (added Section 4A)

### Unchanged (existing validation scripts)
- `scripts/run_trading_gate.py`
- `scripts/run_paper_gate.py`
- `scripts/analyze_gate_results.py`

---

## Testing

Validation performed locally:

```bash
# 1. Scripts can show help
✅ python scripts/run_trading_gate.py --help
✅ python scripts/run_paper_gate.py --help
✅ python scripts/analyze_gate_results.py --help

# 2. Scripts can run dry-run
✅ python scripts/run_paper_gate.py --dry-run

# 3. Documentation structure
✅ All required sections present in runbook
✅ PRE_LIVE_CHECKLIST links to runbook
✅ Thresholds consistent across docs

# 4. CI workflow syntax
✅ YAML is valid
✅ All referenced files exist
```

CI workflow will validate these on every PR/push.

---

## Next Steps (After Merge)

1. **In staging environment**:
   - Follow `STAGING_FULL_TRADING_VALIDATION_RUNBOOK.md`
   - Run 10-minute gate
   - Run 30-minute gate
   - Verify all 5 go/no-go criteria pass

2. **Update PRE_LIVE_CHECKLIST.md**:
   - Mark Section 4A items as ✅ after successful validation
   - Archive gate result JSON files

3. **Before live flip**:
   - Ensure all PRE_LIVE_CHECKLIST sections are ✅
   - Get stakeholder sign-offs (SRE, Trading Lead, Engineering Lead, Risk Manager)

4. **After live flip**:
   - Monitor event loop P95 via `/health/event_loop`
   - Set up alerts for P95 > 400ms
   - Start with conservative live limits (per runbook guidance)

---

## References

- Existing documentation: `VALIDATION_GUIDE.md`, `FULL_TRADING_MODE_GATE_VALIDATION.md`
- Event loop fixes: `fix_history.md`
- Gate validation scripts: `scripts/run_*.py`, `scripts/analyze_*.py`
