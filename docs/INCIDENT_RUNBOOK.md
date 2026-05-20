# Trading Incident Runbook

**Last Updated:** 2026-05-15  
**Scope:** Kalshi 15m Crypto Trading Stack (BTC_15M, ETH_15M, SOL_15M, XRP_15M, DOGE_15M)

## Overview

This runbook provides step-by-step procedures for responding to trading incidents, with specific integration of the risk snapshot and replay harness tools for fee/drawdown anomaly incidents.

---

## Incident Classification

### Severity Levels

- **P0 - Critical**: System-wide trading halt, significant financial loss, risk control failure
- **P1 - High**: Single agent misbehavior, unexpected losses, risk parameter breach
- **P2 - Medium**: Performance degradation, minor configuration issues
- **P3 - Low**: Informational, monitoring gaps

### Incident Types

1. **Risk Control Failure**: Halt/unwind not triggering, limits exceeded
2. **Fee Anomaly**: Unexpected fee rates, missing fees, fee drift
3. **Drawdown Anomaly**: Premature halt, halt not triggering, unwind failure
4. **Configuration Drift**: Profile parameters changed unexpectedly
5. **Execution Failure**: Orders not routing, fills not recording
6. **Data Quality**: Missing or incorrect market data, PnL discrepancies

---

## General Incident Response Procedure

### Phase 1: Initial Triage (0-5 minutes)

1. **Acknowledge Alert**
   - Acknowledge in alerting system (PagerDuty, Slack)
   - Note timestamp and severity

2. **Assess Impact**
   - Check if agents are still trading
   - Check if any agents are halted
   - Check current PnL and drawdown state
   - Check if any risk limits exceeded

3. **Containment (if needed)**
   - If critical: Trigger kill-switch for affected agents
   - If high: Halt affected agents via API
   - If medium: Monitor closely, prepare to halt

4. **Gather Initial Context**
   - Check dashboard for anomaly patterns
   - Check logs for error messages
   - Check recent deployments for changes

### Phase 2: Investigation (5-30 minutes)

5. **Run Risk Snapshot** (Critical for Risk/Drawdown/Fee Incidents)
   ```bash
   python scripts/generate_risk_snapshot.py --output incident_risk_snapshot.json
   ```
   - This captures current profile parameters and agent configuration
   - Compare with pre-deploy snapshot to detect drift
   - Store snapshot for post-mortem analysis

6. **Check Dashboard Metrics**
   - Fee dashboard: Check for fee drift or missing fees
   - Drawdown dashboard: Check for halt/unwind events
   - Aggregate dashboard: Check for systemic issues

7. **Review Logs**
   - Check `_prediction_risk.py` logs for drawdown check execution
   - Check `fees.py` logs for fee calculation errors
   - Check `startup_validations.py` logs for profile validation

8. **Identify Root Cause**
   - Determine if issue is configuration, code, or external (Kalshi)
   - Check if profile parameters are correct
   - Check if canonical primitives are being used

### Phase 3: Resolution (30-60 minutes)

9. **Apply Fix**
   - If configuration: Update profile or agent config
   - If code: Deploy hotfix or rollback
   - If external: Document and monitor

10. **Verify Fix**
    - Run risk snapshot again to confirm parameters correct
    - Check dashboard metrics return to normal
    - Test with small trade if appropriate

11. **Restore Service**
    - Re-enable halted agents (if appropriate)
    - Remove kill-switch
    - Monitor for 30 minutes

### Phase 4: Post-Incident (1-24 hours)

12. **Run Replay Harness** (Critical for Risk/Drawdown/Fee Incidents)
    ```bash
    python scripts/replay_harness.py --fills incident_fills.json --profile kalshi_crypto_15m_v2 --output incident_replay_report.json
    ```
    - This verifies fees and drawdown behavior match expectations
    - Compare replay results with dashboard data
    - Identify any discrepancies

13. **Post-Mortem**
    - Document timeline
    - Document root cause
    - Document resolution
    - Identify preventive measures

---

## Specific Incident Procedures

### Incident Type: Risk Control Failure

**Symptoms:**
- Agent trading when should be halted
- Halt not triggering at expected drawdown
- Unwind not triggering at expected drawdown
- Daily loss cap exceeded

**Procedure:**

1. **Immediate Containment** (0-2 minutes)
   - Trigger kill-switch for affected agent
   - Note current PnL and drawdown state

2. **Run Risk Snapshot** (2-5 minutes)
   ```bash
   python scripts/generate_risk_snapshot.py --output risk_snapshot_fail.json
   ```
   - Check profile parameters (drawdown_halt_pct, drawdown_unwind_pct, max_daily_loss_usd)
   - Compare with pre-deploy snapshot
   - Check if parameters drifted

3. **Check Drawdown Logic** (5-15 minutes)
   - Review `_prediction_risk.py` logs for halt check execution
   - Verify profile is loaded correctly
   - Verify drawdown calculation is accurate
   - Check if peak equity tracking is correct

4. **Run Replay Harness** (15-30 minutes)
   ```bash
   python scripts/replay_harness.py --fills incident_fills.json --profile kalshi_crypto_15m_v2 --output replay_report.json
   ```
   - Verify drawdown path matches expected behavior
   - Check if halt/unwind events should have triggered
   - Compare replay results with actual behavior

5. **Resolution**
   - Fix drawdown logic if incorrect
   - Update profile if threshold was misconfigured
   - Restart agent after fix
   - Monitor for recurrence

**Post-Mortem Questions:**
- Why did halt not trigger?
- Were profile parameters correct?
- Was drawdown calculation accurate?
- Was peak equity tracking correct?
- How can we prevent this in the future?

---

### Incident Type: Fee Anomaly

**Symptoms:**
- Missing or zero fees on fills
- Fee rate drift from expected (7%/5%/3%)
- Fee tier distribution shift
- Total fee spend unexpected

**Procedure:**

1. **Immediate Containment** (0-2 minutes)
   - Halt affected agent if fees are critical
   - Note current fee rate and tier distribution

2. **Run Risk Snapshot** (2-5 minutes)
   ```bash
   python scripts/generate_risk_snapshot.py --output risk_snapshot_fee.json
   ```
   - Check if canonical primitives are being used
   - Check if `fees.py` is being called

3. **Check Fee Dashboard** (5-15 minutes)
   - Check for missing fee count
   - Check fee rate vs expected
   - Check tier distribution
   - Check if Kalshi fee schedule changed

4. **Run Replay Harness** (15-30 minutes)
   ```bash
   python scripts/replay_harness.py --fills incident_fills.json --profile kalshi_crypto_15m_v2 --output replay_fee_report.json
   ```
   - Verify fee calculation matches `fees.py`
   - Compare expected fees with actual fees
   - Identify discrepancies

5. **Resolution**
   - Fix broken path to `fees.py` if missing fees
   - Update `fees.py` if Kalshi changed schedule
   - Update docs if schedule changed
   - Restart agent after fix

**Post-Mortem Questions:**
- Why were fees missing or incorrect?
- Was `fees.py` being called?
- Did Kalshi change fee schedule?
- How can we detect this earlier?
- Should we add more fee monitoring?

---

### Incident Type: Configuration Drift

**Symptoms:**
- Profile parameters changed unexpectedly
- Demo/prod parameters diverge
- Risk limits changed without approval
- Agent behavior changed without deployment

**Procedure:**

1. **Immediate Containment** (0-2 minutes)
   - Halt affected agents if risk limits changed
   - Note current configuration

2. **Run Risk Snapshot** (2-5 minutes)
   ```bash
   python scripts/generate_risk_snapshot.py --output risk_snapshot_drift.json
   ```
   - Compare with pre-deploy snapshot
   - Identify which parameters changed
   - Check if change was intentional

3. **Check Deployment History** (5-15 minutes)
   - Review recent deployments
   - Check changelog for intentional changes
   - Check if profile YAML was modified

4. **Check Demo/Prod Parity** (15-30 minutes)
   - Compare demo and prod risk snapshots
   - Identify divergent parameters
   - Verify if differences are allowed

5. **Resolution**
   - Revert if change was unintentional
   - Document if change was intentional
   - Update baseline snapshot
   - Add validation to prevent future drift

**Post-Mortem Questions:**
- Why did configuration drift?
- Was change intentional or accidental?
- Was proper approval process followed?
- How can we prevent future drift?
- Should we add more configuration monitoring?

---

## Integration with Alert Rules

### DD Anomaly Alert Runbook Integration

When a drawdown anomaly alert fires (from `docs/alert_rules.md`), the runbook explicitly includes:

1. **Pull the snapshot for the deployment that was live when the anomaly occurred**
   - Find the risk snapshot from the deployment timestamp
   - Load snapshot: `risk_snapshot_pre_deploy.json`
   - Check profile parameters at time of incident

2. **Run the replay harness against that agent's fills**
   ```bash
   python scripts/replay_harness.py --fills agent_fills.json --profile kalshi_crypto_15m_v2 --output replay_dd_report.json
   ```
   - Compare replay results with dashboard data
   - Verify drawdown behavior matches expectations

3. **Compare with what dashboards showed**
   - Check fee dashboard for fee anomalies
   - Check drawdown dashboard for halt/unwind events
   - Identify discrepancies between replay and actual

This ties the scripts into the operational muscle memory recommended in formal best-practice docs.

---

## Runbook Maintenance

### Review Cadence
- **Monthly**: Review runbook for accuracy
- **Quarterly**: Update based on new incident learnings
- **Annually**: Major revision based on system changes

### Update Triggers
- New incident type discovered
- New tool or script added
- System architecture change
- Alert rule change
- Profile configuration change

### Training
- All on-call engineers should review runbook quarterly
- Run drills for P0/P1 incidents quarterly
- Document runbook improvements after each incident

---

## References

- `docs/risk_primitives.md` - Canonical primitives documentation
- `docs/alert_rules.md` - Alert rules and response procedures
- `scripts/generate_risk_snapshot.py` - Risk snapshot generator
- `scripts/replay_harness.py` - Backtest/live equivalence verification
- `docs/dashboard_requirements.md` - Dashboard requirements
- `docs/STRATEGY_ONBOARDING.md` - Strategy onboarding guide

---

## Kalshi 15m Crypto Incidents

For Kalshi 15-minute crypto market-specific incidents, refer to:

- `docs/audit/KALSHI_RECONCILIATION_AUDIT.md` - Reconciliation invariants, phantom detection, and resolution procedures
- `docs/audit/KALSHI_RISK_EXTERNAL_CONTRACT.md` - Risk infrastructure, exposure caps, and kill-switch behavior
- `docs/audit/KALSHI_EXTERNAL_CONTRACT.md` - Kalshi API contract, series tickers, and market discovery

These documents provide venue-specific guidance for troubleshooting position discrepancies, risk limit breaches, and API behavior changes in the Kalshi 15m crypto stack.
