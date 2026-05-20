# Fee and Drawdown Alert Rules

**Last Updated:** 2026-05-14  
**Scope:** Kalshi 15m Crypto Trading Stack (BTC_15M, ETH_15M, SOL_15M, XRP_15M, DOGE_15M)

## Overview

This document defines alert rules for detecting anomalies in fee and drawdown behavior. These alerts fire when invariants derived from the canonical primitives are violated, indicating potential bugs, configuration drift, or external changes (e.g., Kalshi fee schedule changes).

---

## Alert Severity Levels

- **HIGH**: Immediate action required - system may be trading with incorrect risk parameters
- **MEDIUM**: Investigation required - potential issue that may escalate
- **LOW**: Informational - may indicate drift or need for tuning

---

## 1. Fee Anomaly Alerts

### Alert 1.1: Missing or Zero Fee

**Severity:** HIGH  
**Condition:** An agent trades but fee records are missing or zero  
**Metric:** Count of fills with `fee_cents = 0` or `fee_cents = None` in last 5 minutes  
**Threshold:** > 0  
**Duration:** Immediate  
**Description:** Indicates a broken path to `fees.py` or data corruption in fill recording  

**Alert Message:**
```
[FEE-ANOMALY] Agent {agent_name} has {count} fills with missing/zero fees in last 5 minutes.
This indicates a broken path to canonical fee calculation (fees.py) or data corruption.
Expected: All fills should have non-zero fees computed via calculate_kalshi_fee_cents().
```

**Investigation Steps:**
1. Check `fills_ledger.py` logs for fee calculation errors
2. Verify `calculate_kalshi_fee_cents()` is being called in order router
3. Check for data corruption in Kalshi API response
4. Verify fee_cents field is being persisted correctly

**Resolution:**
- Fix broken path to `fees.py`
- Restart agent if necessary
- Manually reconcile missing fees for audit trail

---

### Alert 1.2: Fee Drift from Expected Rate

**Severity:** MEDIUM  
**Condition:** Actual fee rate differs from expected rate (from `fees.py` tiers)  
**Metric:** `(actual_fee_rate - expected_fee_rate) / expected_fee_rate`  
**Threshold:** > 1% (0.01) for > 10 fills  
**Duration:** 10 minutes  
**Description:** Indicates Kalshi may have changed fee schedule or tier logic is incorrect  

**Alert Message:**
```
[FEE-DRIFT] Agent {agent_name} fee rate drifted by {drift_pct:.2%} from expected.
Expected rate: {expected_rate:.2%} (from fees.py tiers)
Actual rate: {actual_rate:.2%} (from fills)
Affected fills: {count} in last 10 minutes
Possible cause: Kalshi fee schedule change or tier logic error.
```

**Investigation Steps:**
1. Verify current Kalshi fee schedule at https://kalshi.com/fee-schedule
2. Check if tier boundaries changed (1-99, 100-999, 1000+)
3. Run `replay_harness.py` on recent fills to verify calculation
4. Check if fee tier distribution shifted significantly

**Resolution:**
- Update `fees.py` if Kalshi changed schedule
- Update `docs/risk_primitives.md` with new schedule
- Run CI check to ensure no drift in backtests

---

### Alert 1.3: Tier Distribution Shift

**Severity:** LOW  
**Condition:** Fee tier distribution shifts significantly from baseline  
**Metric:** Change in percentage of fills in each tier  
**Threshold:** > 20% absolute change for any tier  
**Duration:** 1 hour  
**Description:** May indicate strategy behavior change or market regime shift  

**Alert Message:**
```
[TIER-SHIFT] Agent {agent_name} fee tier distribution shifted significantly.
Tier 1-99: {old_pct:.1%} → {new_pct:.1%} (delta: {delta_pct:.1%})
Tier 100-999: {old_pct:.1%} → {new_pct:.1%} (delta: {delta_pct:.1%})
Tier 1000+: {old_pct:.1%} → {new_pct:.1%} (delta: {delta_pct:.1%})
May indicate strategy behavior change or market regime shift.
```

**Investigation Steps:**
1. Check if strategy parameters changed (position sizing, edge thresholds)
2. Check if market volatility changed (affects typical fill sizes)
3. Review recent strategy decisions for unusual patterns

**Resolution:**
- If intentional (strategy change): update baseline distribution
- If unintentional: investigate strategy logic

---

## 2. Drawdown Anomaly Alerts

### Alert 2.1: Agent Active When Should Be Halted

**Severity:** HIGH  
**Condition:** Agent remains active while PnL is below `max_daily_loss_usd` by > 10%  
**Metric:** `daily_loss_usd / max_daily_loss_usd`  
**Threshold:** < -1.10 (110% of daily loss cap exceeded)  
**Duration:** 1 minute  
**Description:** Halt didn't trigger - critical risk control failure  

**Alert Message:**
```
[DRAWDOWN-HALT-FAIL] Agent {agent_name} is active but daily loss exceeds cap.
Daily loss: ${daily_loss:.2f}
Max daily loss cap: ${max_daily_loss_usd:.2f}
Exceeded by: {exceed_pct:.1%}
Current drawdown: {drawdown_pct:.2%}
Halt threshold: {halt_pct:.2%}
CRITICAL: Risk control failure - halt did not trigger.
```

**Investigation Steps:**
1. Check `_prediction_risk.py` logs for halt check execution
2. Verify `max_daily_loss_usd` is loaded from profile correctly
3. Check if profile gating is bypassed or disabled
4. Verify agent state machine respects halt signal

**Runbook Integration:**
- Pull the risk snapshot for the deployment that was live when the anomaly occurred:
  ```bash
  python scripts/generate_risk_snapshot.py --output incident_risk_snapshot.json
  ```
- Run the replay harness against that agent's fills:
  ```bash
  python scripts/replay_harness.py --fills agent_fills.json --profile kalshi_crypto_15m_v2 --output replay_report.json
  ```
- Compare replay results with dashboard data to identify discrepancies

**Resolution:**
- Fix halt check logic in `_prediction_risk.py`
- Manually halt agent immediately
- Review all fills since halt should have triggered

---

### Alert 2.2: Premature Halt

**Severity:** MEDIUM  
**Condition:** Agent halted while drawdown is < 50% of halt threshold  
**Metric:** `current_drawdown / drawdown_halt_pct`  
**Threshold:** < 0.50  
**Duration:** Immediate  
**Description:** Halt triggered too early - may be calculation error or bug  

**Alert Message:**
```
[DRAWDOWN-PREMATURE-HALT] Agent {agent_name} halted prematurely.
Current drawdown: {drawdown_pct:.2%}
Halt threshold: {halt_pct:.2%}
Drawdown is only {ratio:.1%} of halt threshold.
Possible cause: Calculation error, bug, or incorrect profile values.
```

**Investigation Steps:**
1. Verify drawdown calculation in `_prediction_risk.py`
2. Check if `drawdown_halt_pct` is correct in profile YAML
3. Verify peak equity tracking is accurate
4. Check for negative equity or other edge cases

**Runbook Integration:**
- Pull the risk snapshot for the deployment that was live when the anomaly occurred:
  ```bash
  python scripts/generate_risk_snapshot.py --output incident_risk_snapshot.json
  ```
- Run the replay harness against that agent's fills:
  ```bash
  python scripts/replay_harness.py --fills agent_fills.json --profile kalshi_crypto_15m_v2 --output replay_report.json
  ```
- Compare replay results with dashboard data to verify drawdown calculation

**Resolution:**
- Fix drawdown calculation if incorrect
- Update profile if threshold was misconfigured
- Restart agent after fix

---

### Alert 2.3: Unwind Not Triggered

**Severity:** MEDIUM  
**Condition:** Unwind not triggered when drawdown > unwind threshold  
**Metric:** `current_drawdown >= drawdown_unwind_pct` and `unwind_mode = false`  
**Threshold:** True  
**Duration:** 1 minute  
**Description:** Unwind mode should be active but isn't  

**Alert Message:**
```
[DRAWDOWN-UNWIND-FAIL] Agent {agent_name} unwind not triggered.
Current drawdown: {drawdown_pct:.2%}
Unwind threshold: {unwind_pct:.2%}
Unwind mode: {unwind_mode}
Unwind should be active but isn't.
```

**Investigation Steps:**
1. Check `_prediction_risk.py` unwind check logic
2. Verify `drawdown_unwind_pct` is loaded from profile correctly
3. Check if unwind mode flag is being set correctly
4. Verify agent respects unwind mode in position sizing

**Runbook Integration:**
- Pull the risk snapshot for the deployment that was live when the anomaly occurred:
  ```bash
  python scripts/generate_risk_snapshot.py --output incident_risk_snapshot.json
  ```
- Run the replay harness against that agent's fills:
  ```bash
  python scripts/replay_harness.py --fills agent_fills.json --profile kalshi_crypto_15m_v2 --output replay_report.json
  ```
- Compare replay results with dashboard data to verify unwind behavior

**Resolution:**
- Fix unwind check logic
- Update profile if threshold was misconfigured

---

### Alert 2.4: Daily Loss Exceeded

**Severity:** HIGH  
**Condition:** Daily loss exceeds `max_daily_loss_usd` by > 5%  
**Metric:** `daily_loss_usd / max_daily_loss_usd`  
**Threshold:** < -1.05  
**Duration:** 1 minute  
**Description:** Daily loss cap exceeded - should have halted  

**Alert Message:**
```
[DRAWDOWN-DAILY-LOSS] Agent {agent_name} daily loss exceeded cap.
Daily loss: ${daily_loss:.2f}
Max daily loss cap: ${max_daily_loss_usd:.2f}
Exceeded by: {exceed_pct:.1%}
Agent should have halted at cap.
```

**Investigation Steps:**
1. Same as Alert 2.1 (halt failure investigation)
2. Additional: Check if daily loss tracking is cumulative correctly

**Runbook Integration:**
- Pull the risk snapshot for the deployment that was live when the anomaly occurred:
  ```bash
  python scripts/generate_risk_snapshot.py --output incident_risk_snapshot.json
  ```
- Run the replay harness against that agent's fills:
  ```bash
  python scripts/replay_harness.py --fills agent_fills.json --profile kalshi_crypto_15m_v2 --output replay_report.json
  ```
- Compare replay results with dashboard data to verify daily loss tracking

**Resolution:**
- Same as Alert 2.1

---

## 3. Profile Drift Alerts

### Alert 3.1: Profile Parameter Change

**Severity:** MEDIUM  
**Condition:** Profile parameters changed between deployments  
**Metric:** Diff of current profile vs baseline snapshot  
**Threshold:** Any change to `drawdown_halt_pct`, `drawdown_unwind_pct`, `max_daily_loss_usd`  
**Duration:** On deployment  
**Description:** Risk parameters changed - may be intentional or accidental  

**Alert Message:**
```
[PROFILE-DRIFT] Profile {profile_name} parameters changed.
Changed parameters:
- drawdown_halt_pct: {old_value} → {new_value}
- drawdown_unwind_pct: {old_value} → {new_value}
- max_daily_loss_usd: {old_value} → {new_value}
Deployment: {deployment_id}
Verify this change was intentional.
```

**Investigation Steps:**
1. Review deployment changelog for intentional changes
2. Check if profile YAML was modified
3. Verify change aligns with risk appetite

**Resolution:**
- If intentional: document change and update baseline
- If accidental: revert deployment or fix profile

---

### Alert 3.2: Demo/Prod Parameter Divergence

**Severity:** HIGH  
**Condition:** Demo and prod have different drawdown parameters (except allowed differences)  
**Metric:** Diff of demo profile vs prod profile  
**Threshold:** Any difference in `drawdown_halt_pct`, `drawdown_unwind_pct`, `min_post_fee_edge`, `max_spread_pct`  
**Duration:** On deployment  
**Description**: Demo and prod should have identical risk logic  

**Alert Message:**
```
[DEMO-PROD-DIVERGENCE] Demo and prod risk parameters differ.
Divergent parameters:
- drawdown_halt_pct: demo={demo_value}, prod={prod_value}
- drawdown_unwind_pct: demo={demo_value}, prod={prod_value}
Allowed differences: max_notional_usd, max_daily_loss_usd, capital_usd
This may cause behavior differences between environments.
```

**Investigation Steps:**
1. Review profile YAMLs for demo and prod
2. Verify if differences are intentional (e.g., testing)
3. Check if demo should mirror prod exactly

**Resolution:**
- Align demo and prod parameters
- Document intentional differences if any

---

## 4. System Health Alerts

### Alert 4.1: Canonical Module Missing

**Severity:** HIGH  
**Condition:** Canonical fee or drawdown module not found or failed to import  
**Metric:** Import success of `fees.py`, `_prediction_risk.py`, `crypto_15m_profile.py`  
**Threshold:** Import failure  
**Duration:** On startup  
**Description**: Critical primitives unavailable - system cannot trade safely  

**Alert Message:**
```
[MODULE-MISSING] Canonical risk primitive module failed to import.
Module: {module_name}
Error: {error_message}
System cannot trade safely without canonical primitives.
```

**Investigation Steps:**
1. Check if file was deleted or moved
2. Check for syntax errors or import dependencies
3. Verify git history for accidental deletion

**Resolution:**
- Restore missing module from git
- Fix import errors
- Restart system

---

### Alert 4.2: Profile Validation Failed

**Severity:** HIGH  
**Condition:** Profile validation failed at startup  
**Metric:** Validation errors from `validate_15m_crypto_profile_fields()`  
**Threshold:** Any validation error  
**Duration:** On startup  
**Description**: Profile has missing or invalid fields - cannot use  

**Alert Message:**
```
[PROFILE-VALIDATION-FAIL] Profile {profile_name} validation failed.
Errors:
- {error_1}
- {error_2}
Profile cannot be used with missing or invalid fields.
```

**Investigation Steps:**
1. Review profile YAML for missing required fields
2. Check field values are in valid ranges
3. Verify profile template was used correctly

**Resolution:**
- Fix profile YAML according to template
- Re-run validation

---

## 5. Alert Configuration

### Environment Variables

```bash
# Alert thresholds (can be overridden)
MERID_ALERT_FEE_DRIFT_PCT=0.01          # 1% drift threshold
MERID_ALERT_DRAWDOWN_HALT_FAIL_PCT=0.10  # 10% exceed threshold
MERID_ALERT_DRAWDOWN_PREMATURE_PCT=0.50  # 50% of threshold
MERID_ALERT_TIER_SHIFT_PCT=0.20          # 20% tier shift threshold

# Alert destinations
MERID_ALERT_SLACK_WEBHOOK=https://hooks.slack.com/...
MERID_ALERT_PAGERDUTY_API_KEY=...
MERID_ALERT_EMAIL_RECIPIENTS=ops@example.com

# Alert suppression (for maintenance windows)
MERID_ALERT_SUPPRESS=false
```

### Alert Routing

| Alert Type | Default Routing | On-Call | Slack |
|------------|----------------|---------|-------|
| HIGH severity | PagerDuty + Email | ✅ | ✅ |
| MEDIUM severity | Slack + Email | ❌ | ✅ |
| LOW severity | Email only | ❌ | ❌ |

### Alert Suppression

For planned maintenance or testing:
```bash
export MERID_ALERT_SUPPRESS=true
# Perform maintenance
unset MERID_ALERT_SUPPRESS
```

---

## 6. Testing Alert Rules

### Unit Tests

- Test each alert condition with synthetic data
- Verify alert fires at exact threshold
- Verify alert doesn't fire below threshold
- Test alert message formatting

### Integration Tests

- Deploy test environment with intentionally bad config
- Verify alerts fire as expected
- Verify alert routing works correctly
- Test alert suppression mechanism

### Regression Tests

- Run `replay_harness.py` on historical data
- Verify alerts would have fired for known past issues
- Verify no false positives on normal operation

---

## 7. Alert Response Playbook

### Immediate Response (HIGH severity)

1. **Acknowledge alert** in alerting system
2. **Assess impact**: Is agent trading? Is risk control working?
3. **Contain**: Halt affected agents if necessary
4. **Investigate**: Follow investigation steps in alert definition
5. **Resolve**: Apply fix or rollback
6. **Verify**: Confirm fix works and alerts clear
7. **Document**: Update runbook with lessons learned

### Standard Response (MEDIUM severity)

1. **Acknowledge alert**
2. **Investigate**: Determine root cause
3. **Resolve**: Apply fix or monitor if informational
4. **Document**: Update runbook if needed

### Low Priority (LOW severity)

1. **Review alert** during daily standup
2. **Decide**: Action required or informational?
3. **Act**: Apply fix or update baseline
4. **Document**: Note for future reference

---

## 8. Alert Metrics

Track the following metrics to evaluate alert effectiveness:

- **Alert frequency**: Number of alerts per week by severity
- **False positive rate**: Alerts fired that required no action
- **Mean time to acknowledge**: Time from alert firing to acknowledgment
- **Mean time to resolve**: Time from acknowledgment to resolution
- **Alert fatigue**: Repeated alerts for same issue

Use these metrics to tune thresholds and improve alert quality.
