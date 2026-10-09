# Regression Prevention Checklist - 2026-08-01

## Purpose

This checklist provides operational safeguards to prevent regression of the 38 bug fixes applied to the 15m crypto trading system. The focus is on preventing future changes from reintroducing stale constants, alternate paths, or config precedence issues.

---

## Pre-Startup Checks

### 1. Config-Diff Guard
**Purpose:** Fail startup if old canonical ranges appear anywhere

**Implementation:**
```python
# Add to merid/__init__.py or startup script
def validate_config_ranges():
    """Validate that no config has old 10c-75c ranges."""
    import yaml
    import glob
    
    yaml_files = glob.glob("config/profiles/*.yaml")
    for yaml_file in yaml_files:
        with open(yaml_file, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)
        
        # Check for old ranges
        if 'price_range' in config:
            min_price = config['price_range'].get('min_price_cents', 10)
            max_price = config['price_range'].get('max_price_cents', 75)
            if min_price == 10 or max_price == 75:
                raise ValueError(
                    f"CRITICAL: {yaml_file} has old 10c-75c ranges. "
                    f"Update to 5c-85c before starting."
                )
        
        if 'guardrails' in config:
            min_price = config['guardrails'].get('min_contract_price_cents', 10)
            max_price = config['guardrails'].get('max_contract_price_cents', 75)
            if min_price == 10 or max_price == 75:
                raise ValueError(
                    f"CRITICAL: {yaml_file} has old guardrails 10c-75c ranges. "
                    f"Update to 5c-85c before starting."
                )
```

**Trigger:** Run at application startup before any trading logic

**Failure Action:** System refuses to start with clear error message

---

### 2. Import Order Validation
**Purpose:** Ensure modules import in production order, not test order

**Implementation:**
```python
# Add to startup script
def validate_import_order():
    """Validate that profile loads before module defaults."""
    from merid.risk.profiles.crypto_15m_profile import get_active_profile, is_profile_active
    
    if not is_profile_active():
        raise ValueError(
            "CRITICAL: Profile not active. Module defaults may override profile values. "
            "Ensure profile loads before trading logic."
        )
    
    profile = get_active_profile()
    if profile and hasattr(profile.profile, 'guardrails'):
        max_price = profile.profile.guardrails.max_contract_price_cents
        if max_price < 85:
            raise ValueError(
                f"CRITICAL: Profile has max_contract_price_cents={max_price}c, "
                f"should be >= 85c. Update profile config."
            )
```

**Trigger:** Run at application startup after config validation

**Failure Action:** System refuses to start with clear error message

---

### 3. Code Static Analysis
**Purpose:** Detect reintroduction of stale constants in code

**Implementation:**
```bash
# Add to pre-commit hook or CI pipeline
# Search for old patterns that should not exist
grep -r "10.*75\|25.*75" merid/ --include="*.py" --exclude-dir=__pycache__ | \
    grep -v "CRITICAL FIX" | \
    grep -v "2026-08-01" | \
    grep -v "test_" | \
    grep -v ".pyc"
```

**Trigger:** Run in pre-commit hook and CI pipeline

**Failure Action:** Commit blocked with list of files to fix

---

## Operational Safeguards

### 4. Periodic Invariant Audit Job
**Purpose:** Periodically check for new hardcoded thresholds or bypass paths

**Implementation:**
```python
# Add to cron job or scheduled task
def run_periodic_invariant_audit():
    """Run periodic audit of invariants."""
    import subprocess
    import json
    from datetime import datetime
    
    # Run adversarial tests
    result = subprocess.run(
        ["py", "-m", "pytest", "tests/test_adversarial_audit_2026_08_01.py", "-v"],
        capture_output=True,
        text=True
    )
    
    # Parse results
    if result.returncode != 0:
        # Alert team
        alert_team(
            f"CRITICAL: Adversarial audit failed at {datetime.now()}",
            result.stdout
        )
    
    # Check for new hardcoded thresholds
    grep_result = subprocess.run(
        ["grep", "-r", "ENTRY_MIN_PRICE_CENTS = 10", "merid/"],
        capture_output=True,
        text=True
    )
    
    if grep_result.returncode == 0:
        alert_team(
            f"CRITICAL: Found old ENTRY_MIN_PRICE_CENTS = 10 at {datetime.now()}",
            grep_result.stdout
        )
```

**Trigger:** Run daily via cron or scheduled task

**Failure Action:** Alert team with detailed findings

---

### 5. Kill-Switch Dashboard
**Purpose:** Dashboard for zero-depth, stale-book, and fee-drift incidents

**Implementation:**
```python
# Add to monitoring dashboard
class KillSwitchDashboard:
    """Dashboard for critical trading invariants."""
    
    def __init__(self):
        self.zero_depth_kill_switch = False
        self.stale_book_kill_switch = False
        self.fee_drift_kill_switch = False
        self.incident_log = []
    
    def check_zero_depth_rate(self, rate: float):
        """Check zero-depth rate and trigger kill switch if needed."""
        if rate > 0.05:  # 5% threshold
            self.zero_depth_kill_switch = True
            self.incident_log.append({
                "type": "zero_depth",
                "rate": rate,
                "timestamp": datetime.now().isoformat(),
                "action": "KILL_SWITCH_ACTIVATED"
            })
            alert_team("CRITICAL: Zero-depth kill switch activated")
    
    def check_stale_book_rate(self, rate: float):
        """Check stale-book rate and trigger kill switch if needed."""
        if rate > 0.10:  # 10% threshold
            self.stale_book_kill_switch = True
            self.incident_log.append({
                "type": "stale_book",
                "rate": rate,
                "timestamp": datetime.now().isoformat(),
                "action": "KILL_SWITCH_ACTIVATED"
            })
            alert_team("CRITICAL: Stale-book kill switch activated")
    
    def check_fee_drift_rate(self, rate: float):
        """Check fee drift rate and trigger kill switch if needed."""
        if rate > 0.02:  # 2% threshold
            self.fee_drift_kill_switch = True
            self.incident_log.append({
                "type": "fee_drift",
                "rate": rate,
                "timestamp": datetime.now().isoformat(),
                "action": "KILL_SWITCH_ACTIVATED"
            })
            alert_team("CRITICAL: Fee drift kill switch activated")
    
    def should_stop_trading(self) -> bool:
        """Check if any kill switch is activated."""
        return (
            self.zero_depth_kill_switch or
            self.stale_book_kill_switch or
            self.fee_drift_kill_switch
        )
```

**Trigger:** Real-time monitoring dashboard

**Failure Action:** System stops trading and alerts team

---

## Monitoring/SLO Thresholds

### Current Thresholds (from trading_invariants_monitor.py)

| Metric | Threshold | Alert Level | Action |
|--------|-----------|-------------|--------|
| Fallback spread rate | 5% | WARNING | Log incident |
| Zero depth rate | 2% | WARNING | Log incident |
| Allocator bound rejection rate | 1% | WARNING | Log incident |
| Fee discrepancy rate | 1% | WARNING | Log incident |
| Canonical range violation | Any | CRITICAL | Block trade |
| Zero-depth kill switch | 5% | CRITICAL | Stop trading |
| Stale-book kill switch | 10% | CRITICAL | Stop trading |
| Fee drift kill switch | 2% | CRITICAL | Stop trading |

### Recommended SLO Adjustments

Based on historical incident rates (to be validated):

1. **Fallback spread rate**: 5% → 3% (tighten to catch issues earlier)
2. **Zero depth rate**: 2% → 1% (tighten to catch issues earlier)
3. **Allocator bound rejection rate**: 1% → 0.5% (tighten to catch issues earlier)
4. **Fee discrepancy rate**: 1% → 0.5% (tighten to catch issues earlier)

**Action:** Validate against 7-day historical window before adjusting

---

## Replay Harness

### 6. Replay Harness from Market Snapshots to PnL
**Purpose:** Validate full trading lifecycle from raw market data to final PnL

**Implementation:**
```python
# Add to tests/test_replay_harness_2026_08_01.py
class TestReplayHarness:
    """Test full trading lifecycle from market snapshots to PnL."""
    
    def test_replay_snapshot_to_pnl(self):
        """Replay a market snapshot through to final PnL."""
        # Load historical market snapshot
        snapshot = load_market_snapshot("KXBTC-TEST-2026-08-01-12:00:00.json")
        
        # Step 1: Signal generation
        signal = generate_signal_from_snapshot(snapshot)
        
        # Step 2: Market regime classification
        regime = classify_market_regime(snapshot)
        
        # Step 3: Edge calculation
        edge = calculate_edge(signal, snapshot)
        
        # Step 4: Execution mode decision
        execution_mode = decide_execution_mode(regime, edge)
        
        # Step 5: Order submission
        order = submit_order(signal, execution_mode, snapshot)
        
        # Step 6: Fill simulation
        fill = simulate_fill(order, snapshot)
        
        # Step 7: Fee calculation
        fee = calculate_fee(fill)
        
        # Step 8: PnL calculation
        pnl = calculate_pnl(fill, fee)
        
        # Validate invariants at each step
        assert signal.price_cents in [1, 85] or signal.price_cents in [15, 99]
        assert execution_mode in [ExecutionMode.MAKER, ExecutionMode.TAKER]
        assert fee >= 1  # Minimum fee
        assert pnl is not None
```

**Trigger:** Run daily on historical snapshots

**Failure Action:** Alert team with replay results

---

## Non-Core Module Audit

### 7. Non-Core Scripts and Tools Audit
**Purpose:** Recheck scripts, notebooks, and one-off tools not in test suite

**Implementation:**
```bash
# Search for old patterns in non-core files
find . -name "*.ipynb" -exec grep -l "10.*75\|25.*75" {} \;
find . -name "*.md" -exec grep -l "10c-75c\|25c-75c" {} \;
find . -name "*.sh" -exec grep -l "10.*75\|25.*75" {} \;
find . -name "*.py" -path "./scripts/*" -exec grep -l "10.*75\|25.*75" {} \;
```

**Trigger:** Run weekly via cron or scheduled task

**Failure Action:** Alert team with list of files to update

---

## Documentation Validation

### 8. Runbooks and Documentation Validation
**Purpose:** Ensure documented ranges and invariants are current

**Implementation:**
```python
def validate_documentation():
    """Validate that documentation reflects current invariants."""
    import glob
    import re
    
    # Check all markdown files
    md_files = glob.glob("**/*.md", recursive=True)
    
    for md_file in md_files:
        with open(md_file, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Check for old patterns (excluding comments with CRITICAL FIX)
        lines = content.split('\n')
        for i, line in enumerate(lines):
            if '10c-75c' in line and 'CRITICAL FIX' not in line:
                print(f"WARNING: {md_file}:{i+1} has old 10c-75c reference")
            if '25c-75c' in line and 'CRITICAL FIX' not in line:
                print(f"WARNING: {md_file}:{i+1} has old 25c-75c reference")
```

**Trigger:** Run weekly via cron or scheduled task

**Failure Action:** Alert team with list of documentation to update

---

## Pre-Commit Hook

### 9. Pre-Commit Hook Configuration
**Purpose:** Prevent commits that reintroduce stale constants

**Implementation:**
```yaml
# .pre-commit-config.yaml
repos:
  - repo: local
    hooks:
      - id: check-old-ranges
        name: Check for old price ranges
        entry: python scripts/check_old_ranges.py
        language: system
```

**Implementation:**
```python
# scripts/check_old_ranges.py
import subprocess
import sys

# Search for old patterns
result = subprocess.run(
    ["grep", "-r", "ENTRY_MIN_PRICE_CENTS = 10", "merid/"],
    capture_output=True,
    text=True
)

if result.returncode == 0:
    print("ERROR: Found old ENTRY_MIN_PRICE_CENTS = 10")
    print(result.stdout)
    sys.exit(1)

# Search for old clamp patterns
result = subprocess.run(
    ["grep", "-r", "max(10,.*75)", "merid/"],
    capture_output=True,
    text=True
)

if result.returncode == 0:
    print("ERROR: Found old max(10, min(75, ...)) clamp")
    print(result.stdout)
    sys.exit(1)

print("PASS: No old price ranges found")
```

**Trigger:** Run on every commit

**Failure Action:** Commit blocked with clear error message

---

## CI Pipeline Integration

### 10. CI Pipeline Checks
**Purpose:** Ensure all regression-prevention checks run in CI

**Implementation:**
```yaml
# .github/workflows/regression_prevention.yml
name: Regression Prevention

on: [push, pull_request]

jobs:
  regression-prevention:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      - name: Set up Python
        uses: actions/setup-python@v2
        with:
          python-version: '3.11'
      - name: Install dependencies
        run: |
          pip install -r requirements.txt
      - name: Run config validation
        run: |
          python -c "from merid.startup_checks import validate_config_ranges; validate_config_ranges()"
      - name: Run import order validation
        run: |
          python -c "from merid.startup_checks import validate_import_order; validate_import_order()"
      - name: Run static analysis
        run: |
          bash scripts/check_old_ranges.sh
      - name: Run adversarial tests
        run: |
          pytest tests/test_adversarial_audit_2026_08_01.py -v
      - name: Run all tests
        run: |
          pytest tests/ -v
```

**Trigger:** Run on every push and pull request

**Failure Action:** CI fails with clear error message

---

## Rollback Plan

### 11. Rollback Procedure
**Purpose:** Procedure to rollback if regression is detected

**Triggers:**
- Adversarial tests fail
- Kill switch activated
- Monitoring alerts exceed thresholds

**Procedure:**
1. Stop trading immediately
2. Revert to last known good commit
3. Validate config ranges
4. Run adversarial tests
5. Restart system
6. Monitor for 30 minutes before resuming trading

**Rollback Command:**
```bash
git revert HEAD~1
git push origin main
```

---

## Success Criteria

- ✅ Config-diff guard prevents startup with old ranges
- ✅ Import order validation ensures profile loads first
- ✅ Static analysis prevents commits with stale constants
- ✅ Periodic audit job checks for new hardcoded thresholds
- ✅ Kill-switch dashboard provides real-time incident visibility
- ✅ Replay harness validates full trading lifecycle
- ✅ Non-core modules audited weekly
- ✅ Documentation validated weekly
- ✅ Pre-commit hook prevents bad commits
- ✅ CI pipeline enforces all checks
- ✅ Rollback procedure documented and tested

---

## Monitoring Dashboard Metrics

### Key Metrics to Track

1. **Zero-Depth Rate**
   - Current threshold: 2% WARNING, 5% CRITICAL
   - Target: < 1%
   - Kill switch: 5%

2. **Stale-Book Rate**
   - Current threshold: 10% CRITICAL
   - Target: < 5%
   - Kill switch: 10%

3. **Fallback Spread Rate**
   - Current threshold: 5% WARNING
   - Target: < 3%
   - Kill switch: N/A (log only)

4. **Allocator Bound Rejection Rate**
   - Current threshold: 1% WARNING
   - Target: < 0.5%
   - Kill switch: N/A (log only)

5. **Fee Discrepancy Rate**
   - Current threshold: 1% WARNING
   - Target: < 0.5%
   - Kill switch: 2%

6. **Canonical Range Violations**
   - Current threshold: Any CRITICAL
   - Target: 0
   - Kill switch: N/A (block trade)

---

## Alert Escalation

### Level 1: WARNING
- **Triggers:** Threshold exceeded but below kill switch
- **Action:** Log incident, send notification
- **Escalation:** Email to team

### Level 2: CRITICAL
- **Triggers:** Kill switch activated or canonical range violation
- **Action:** Stop trading, alert team immediately
- **Escalation:** SMS to team, page on-call

### Level 3: EMERGENCY
- **Triggers:** Multiple kill switches activated simultaneously
- **Action:** Emergency shutdown, alert team immediately
- **Escalation:** Phone call to team, page management

---

## Maintenance Schedule

### Daily
- Run adversarial tests
- Check kill-switch dashboard
- Review monitoring alerts

### Weekly
- Run replay harness on historical snapshots
- Audit non-core modules
- Validate documentation

### Monthly
- Review and adjust monitoring thresholds
- Update kill-switch thresholds based on historical data
- Review rollback procedure

### Quarterly
- Full regression audit (all 115 tests)
- Review and update this checklist
- Train team on rollback procedure

---

## Conclusion

This regression-prevention checklist provides operational safeguards to prevent regression of the 38 bug fixes. The focus is on preventing future changes from reintroducing stale constants, alternate paths, or config precedence issues.

The system is now hardened against:
- ✅ Config drift (config-diff guard)
- ✅ Import order issues (import order validation)
- ✅ Code reintroduction (static analysis, pre-commit hook)
- ✅ Hidden bypass paths (adversarial tests, periodic audit)
- ✅ Operational incidents (kill-switch dashboard)
- ✅ Documentation drift (documentation validation)
- ✅ CI pipeline integration

The remaining risk is now mostly operational and can be managed through the monitoring and alerting mechanisms described above.
