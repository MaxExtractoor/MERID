# Parameter Change Protocol

**Purpose:** Formalize the operational protocol for making profile parameter changes in the 15m crypto trading system.

**Scope:** kalshi_crypto_15m_v2 profile YAML changes (edge thresholds, distance filters, Kelly parameters)

---

## Protocol Overview

This protocol ensures repeatable, documented iterations and prevents drift by leveraging existing infrastructure:
- Preflight gate via `validate_profile_envelope_chain()`
- Profile snapshot + diff logging at startup
- Forensics-based analysis and guard-reason counts

---

## Step-by-Step Procedure

### Step 1: Make Profile YAML Change

Edit `config/profiles/kalshi_crypto_15m.yaml`:

1. **Identify the parameter to change** based on forensics analysis (see `docs/15m_calibration_playbook.md`)
2. **Edit the parameter** with incremental adjustments:
   - Edge thresholds: 0.2-0.3% increments
   - Distance filters: 0.5% increments
   - Kelly parameters: 0.05 increments
3. **Add a comment** documenting the change with:
   - Date
   - Forensics report reference
   - Bucket evidence
   - Expected outcome

**Example:**
```yaml
# DOGE late window edge threshold
# Tuned 2026-05-18 based on forensics 2026-05-18_1200
# Evidence: late window 3-4% distance bucket EV=-0.02 (25 trades)
# Expected: Reduce late-window negative EV trades
min_edge_late: 0.033  # Increased from 0.030
```

### Step 2: Validate Configuration

Run the validation script to ensure configuration consistency:

```bash
python scripts/validate_profile_envelope_capability.py
```

**Expected output:** All validations pass (✓ PASS for each check)

**If validation fails:**
- Review the error message
- Fix the configuration inconsistency
- Re-run validation until all checks pass

**Alternative:** Rely on startup preflight gate (will run automatically on next restart)

### Step 3: Restart 15m Worker

Restart the MeridLoop worker to apply the new configuration:

```bash
# If running as service
sudo systemctl restart merid-crypto-bot

# Or if running manually
# Stop the current process and restart
```

### Step 4: Verify Startup

Check startup logs for:

1. **Preflight gate status:**
   ```
   [STARTUP VALIDATION SEQUENCE]
   PREFLIGHT GATE: Profile → Envelope → Capability Validation
   ✓ PASS: profile_yaml
   ✓ PASS: risk_envelope
   ✓ PASS: capability_store
   ✓ PASS: edge_thresholds
   ✓ PASS: adapter_config
   ✓ PREFLIGHT GATE PASSED
   ```

2. **Profile diff:**
   ```
   [PROFILE-DIFF] Configuration Change Detection
   ~ min_edge_late: 0.030 → 0.033
   [PROFILE-DIFF] 1 parameter changes detected
   ```

3. **Confirm only intended parameters changed:**
   - Review the diff output
   - Ensure no unexpected changes

### Step 5: Calibration Window

Run the system for a calibration window:

- **Duration:** 1-3 days OR 50-100 trades per asset (whichever comes first)
- **Monitor:** Kill-switch status, error budget, loop health
- **Collect:** Forensics logs and fills data

### Step 6: Generate Performance Report

After calibration window:

```bash
# Parse logs and generate forensics JSON
python scripts/analyze_15m_forensics.py --log-file server_diag.log --output data/forensics/15m/YYYYMMDD_HHMM.json

# Generate performance report
python scripts/report_15m_performance.py --forensics-dir data/forensics/15m --output data/forensics/15m_performance_report.md
```

### Step 7: Evaluate and Decide

Review the performance report and decide:

**Option A: Keep changes**
- If performance improved or stable
- If negative EV buckets reduced
- If guard reasons balanced
- Document decision in calibration notes

**Option B: Tighten further**
- If negative EV persists but reduced
- Apply additional tuning (return to Step 1 with new adjustment)
- Document iteration

**Option C: Roll back**
- If performance degraded
- If new negative EV buckets appeared
- If kill-switch triggered

**Rollback procedure:**
1. Restore previous YAML from `data/profile_snapshots/last.json` (timestamped snapshot)
2. Re-run validation (Step 2)
3. Restart worker (Step 3)
4. Document rollback reason in calibration notes

---

## Rollback Procedure

If a parameter change degrades performance:

### Option 1: Restore from Snapshot

1. Locate previous snapshot in `data/profile_snapshots/`
2. Find the timestamped JSON file before the change
3. Extract the signature dict to see previous parameter values
4. Manually restore YAML to previous values
5. Re-run validation and restart

### Option 2: Git Rollback

If the change is tracked in git:

```bash
# View git diff
git diff config/profiles/kalshi_crypto_15m.yaml

# Revert the change
git checkout HEAD -- config/profiles/kalshi_crypto_15m.yaml

# Restart worker
```

### Option 3: Manual Revert

Manually edit the YAML file to restore previous parameter values based on:
- Calibration notes documentation
- Git history
- Snapshot data

---

## Documentation Requirements

Every parameter change must be documented in calibration notes with:

1. **Date** of change
2. **Parameter changed** (name, before → after)
3. **Forensics report reference** (YYYYMMDD_HHMM)
4. **Bucket evidence** (prob_band × phase × distance, EV, trade count)
5. **Rule applied** (from calibration playbook)
6. **Expected outcome**
7. **Actual outcome** (after calibration window)
8. **Decision** (keep / tighten / rollback)

**Example:**
```
2026-05-18: DOGE late min_edge 3.0%→3.3%
- Forensics: 2026-05-18_1200
- Evidence: late window, 3-4% distance bucket, EV=-0.02, 25 trades
- Rule: Rule 1 (negative EV bucket)
- Expected: Reduce late-window negative EV trades
- Actual (2026-05-20): Late-window EV improved to +0.01, trades reduced by 30%
- Decision: Keep changes
```

---

## Guardrails

### Never Tune These (Risk Envelope)

These parameters are controlled by the risk envelope and should not be tuned via this protocol:

- `capital_usd`, `profile_capital_usd` (bankroll allocation)
- `max_daily_loss_pct`, `max_daily_loss_usd` (daily risk budget)
- `asset_max_notional_usd` (per-asset caps)
- `max_single_order_notional_usd`, `max_total_notional_usd` (venue caps)
- `drawdown_halt_pct`, `drawdown_unwind_pct` (drawdown limits)

### Change Incrementally

- Adjust edge thresholds in 0.2-0.3% increments
- Adjust distance in 0.5% increments
- Adjust Kelly in 0.05 increments
- Allow at least 50-100 trades between changes per asset

### No Parameter Flapping

- Do not make multiple changes to the same parameter within a single calibration window
- If a change doesn't work, roll back before trying a different adjustment
- Document each iteration separately

### Kill-Switch Override

- Do not make parameter changes while kill-switch is active
- Resolve the kill-switch trigger first (daily loss exceeded, error threshold, etc.)
- Wait for auto-reset at UTC day rollover or manual reset
- Then proceed with parameter change protocol

---

## Integration with Existing Infrastructure

This protocol leverages:

1. **Preflight Gate** (`validate_profile_envelope_chain()`)
   - Automatically runs at startup
   - Validates profile → envelope → capability consistency
   - Aborts startup if validation fails

2. **Profile Snapshot + Diff** (`_log_kalshi_startup_snapshot()`)
   - Automatically logs profile signature at startup
   - Compares with previous snapshot
   - Logs parameter changes

3. **Forensics Logging** (`log_15m_forensics()`)
   - Logs every trade decision (TRADE or NO_TRADE)
   - Includes skip_reason for guard rejections
   - Provides data for calibration decisions

4. **Analysis Script** (`analyze_15m_forensics.py`)
   - Parses forensics logs
   - Computes bucketed EV/win rate
   - Counts guard reasons per asset

5. **Performance Dashboard** (`report_15m_performance.py`)
   - Generates markdown report per asset
   - Shows best/worst buckets
   - Shows guard reason distribution

6. **Regression Tests** (`test_15m_regression.py`)
   - Tests guard behavior (edge, distance, kill-switch)
   - Protects pipeline from regressions
   - Run before deploying changes

---

## Success Metrics

A well-executed parameter change should show:

- Preflight gate passes on startup
- Profile diff shows only intended parameter changes
- No unexpected configuration errors
- Performance report shows improvement or stability
- No regression in win rate or EV
- No increase in guard rejections for unintended reasons
- System remains stable (no watchdog trips, no kill-switch triggers)

---

## Emergency Procedure

If a parameter change causes immediate issues (e.g., sudden spike in losses, kill-switch triggers):

1. **Immediate rollback:**
   - Restore previous YAML values
   - Restart worker immediately

2. **Incident documentation:**
   - Document what happened
   - Document rollback action
   - Document timeline

3. **Post-incident review:**
   - Analyze why the change caused issues
   - Update calibration playbook if needed
   - Consider additional regression tests

4. **Prevention:**
   - Consider running regression tests before applying future changes
   - Consider smaller incremental changes
   - Consider longer calibration windows
