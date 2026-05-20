# Fee Schedule Impact Analysis Template

**Last Updated:** 2026-05-15  
**Purpose:** Template for analyzing the impact of Kalshi fee schedule changes on strategy performance

---

## Analysis Metadata

**Analysis Date:** YYYY-MM-DD  
**Analyst:** [Name]  
**Fee Schedule Change:** [Description of change]  
**Effective Date:** [YYYY-MM-DD]  
**Analysis Period:** [Start Date] to [End Date]  

---

## Executive Summary

**Brief Summary:** [2-3 sentence summary of key findings]

**Key Metrics:**
- Total PnL Impact: [USD] ([+%/-])
- Fee Rate Change: [percentage points]
- Most Affected Agent: [Agent Name]
- Recommendation: [Deploy / Hold / Adjust Parameters]

---

## Fee Schedule Change Details

### Old Schedule
- Tier 1 (1-99 contracts): [X]%
- Tier 2 (100-999 contracts): [Y]%
- Tier 3 (1000+ contracts): [Z]%
- Minimum fee: [X]¢ per contract

### New Schedule
- Tier 1 (1-99 contracts): [X]%
- Tier 2 (100-999 contracts): [Y]%
- Tier 3 (1000+ contracts): [Z]%
- Minimum fee: [X]¢ per contract

### Change Summary
- Tier 1 rate change: [+/- X percentage points]
- Tier 2 rate change: [+/- Y percentage points]
- Tier 3 rate change: [+/- Z percentage points]
- Tier boundary changes: [Yes/No - describe if any]

---

## Impact Analysis Results

### Overall Impact

| Metric | Old Fees | New Fees | Change | % Change |
|--------|----------|----------|--------|----------|
| Total Fees (USD) | $[X] | $[Y] | $[Z] | [Z]% |
| Total Notional (USD) | $[X] | $[Y] | $[Z] | [Z]% |
| Effective Fee Rate | [X]% | [Y]% | [Z]pp | [Z]% |
| Net PnL (USD) | $[X] | $[Y] | $[Z] | [Z]% |
| Gross PnL (USD) | $[X] | $[Y] | $[Z] | [Z]% |

### Per-Agent Impact

| Agent | Old Fees | New Fees | PnL Impact | Fee Rate Change |
|-------|----------|----------|------------|-----------------|
| BTC_15M | $[X] | $[Y] | $[Z] | [Z]% |
| ETH_15M | $[X] | $[Y] | $[Z] | [Z]% |
| SOL_15M | $[X] | $[Y] | $[Z] | [Z]% |
| XRP_15M | $[X] | $[Y] | $[Z] | [Z]% |
| DOGE_15M | $[X] | $[Y] | $[Z] | [Z]% |

### Tier Distribution Impact

| Tier | Old Count | New Count | Change | % Change |
|------|-----------|-----------|--------|----------|
| 1-99 contracts | [X] | [Y] | [Z] | [Z]% |
| 100-999 contracts | [X] | [Y] | [Z] | [Z]% |
| 1000+ contracts | [X] | [Y] | [Z] | [Z]% |

---

## Replay Harness Results

### Old Fees Replay
- Total Fills: [X]
- Expected Fees: $[X]
- Actual Fees: $[X]
- Match Rate: [X]%
- Halt Events: [X]
- Unwind Events: [X]

### New Fees Replay
- Total Fills: [X]
- Expected Fees: $[X]
- Actual Fees: $[X]
- Match Rate: [X]%
- Halt Events: [X]
- Unwind Events: [X]

### Comparison
- Fee Difference: $[X] ([Z]%)
- PnL Difference: $[X] ([Z]%)
- Halt Event Difference: [X]
- Unwind Event Difference: [X]

---

## Risk-Adjusted Performance

### Sharpe Ratio Comparison

| Agent | Old Fees Sharpe | New Fees Sharpe | Change |
|-------|-----------------|-----------------|--------|
| BTC_15M | [X] | [Y] | [Z] |
| ETH_15M | [X] | [Y] | [Z] |
| SOL_15M | [X] | [Y] | [Z] |
| XRP_15M | [X] | [Y] | [Z] |
| DOGE_15M | [X] | [Y] | [Z] |

### Maximum Drawdown Comparison

| Agent | Old Fees Max DD | New Fees Max DD | Change |
|-------|-----------------|-----------------|--------|
| BTC_15M | [X]% | [Y]% | [Z]% |
| ETH_15M | [X]% | [Y]% | [Z]% |
| SOL_15M | [X]% | [Y]% | [Z]% |
| XRP_15M | [X]% | [Y]% | [Z]% |
| DOGE_15M | [X]% | [Y]% | [Z]% |

---

## Strategy Parameter Recommendations

### Parameters to Adjust

If fee schedule change materially impacts strategy performance, consider adjusting:

1. **Edge Thresholds**
   - Current: [X]%
   - Recommended: [Y]%
   - Reason: [Explanation]

2. **Position Sizing**
   - Current max_notional_usd: $[X]
   - Recommended max_notional_usd: $[Y]
   - Reason: [Explanation]

3. **Drawdown Limits**
   - Current drawdown_halt_pct: [X]%
   - Recommended drawdown_halt_pct: [Y]%
   - Reason: [Explanation]

### No Changes Needed

If impact is minimal (< 5% PnL impact), no parameter adjustments needed.

---

## Deployment Recommendation

### Options

**Option A: Deploy Without Changes**
- Rationale: Impact is minimal ([< 5% PnL impact])
- Risk: Low
- Timeline: Immediate

**Option B: Deploy with Parameter Adjustments**
- Rationale: Impact is significant ([> 5% PnL impact]), adjustments needed
- Risk: Medium
- Timeline: [X] days

**Option C: Hold Deployment**
- Rationale: Impact is too high ([> 20% PnL impact]), needs further analysis
- Risk: Low
- Timeline: Until further analysis

### Recommendation

**Selected Option:** [Option A / B / C]

**Justification:** [2-3 sentences explaining why]

**Deployment Checklist:**
- [ ] fees.py updated with new schedule
- [ ] Documentation updated with version notes
- [ ] Replay harness completed
- [ ] Impact analysis completed
- [ ] Alert thresholds updated (if needed)
- [ ] Dashboard requirements updated (if needed)
- [ ] Strategy parameters adjusted (if needed)
- [ ] Risk team approval obtained
- [ ] Demo deployment tested
- [ ] Production deployment approved
- [ ] Monitoring plan in place
- [ ] Rollback procedure documented

---

## Monitoring Plan

### First 24 Hours

- Monitor fee dashboard for fee drift alerts
- Monitor drawdown dashboard for halt/unwind events
- Check surveillance reconciliation report
- Compare actual fees with expected fees

### First Week

- Daily surveillance reconciliation
- Weekly PnL comparison with baseline
- Review alert frequency
- Check for unintended side effects

### Success Criteria

- Fee rate within expected range ([X]% +/- [Y]%)
- No HIGH severity alerts
- PnL within [X]% of expected
- Drawdown behavior consistent with expectations

---

## Rollback Triggers

If any of the following occur within first week, consider rollback:

- PnL deviates by > [20]% from expected
- Fee rate deviates by > [10]% from expected
- HIGH severity alert fires
- Drawdown behavior significantly different from expected
- Agent halts unexpectedly

---

## Post-Deployment Review

**Review Date:** [YYYY-MM-DD]  
**Reviewers:** [Names]

**Questions:**
1. Did actual fees match expected fees?
2. Was PnL impact within expected range?
3. Were there any unintended side effects?
4. Should any parameters be further adjusted?
5. Should alert thresholds be updated?

**Action Items:**
- [ ] [Action item 1]
- [ ] [Action item 2]
- [ ] [Action item 3]

---

## Appendix: Raw Data

### Replay Harness Output (Old Fees)
```json
{
  "fee_verification": {
    "summary": {...},
    "mismatches": [...]
  },
  "drawdown_simulation": {
    "limits": {...},
    "result": {...}
  }
}
```

### Replay Harness Output (New Fees)
```json
{
  "fee_verification": {
    "summary": {...},
    "mismatches": [...]
  },
  "drawdown_simulation": {
    "limits": {...},
    "result": {...}
  }
}
```

### Surveillance Reconciliation Report
```json
{
  "report_date": "...",
  "date_range": [...],
  "results": [...],
  "warnings": [...]
}
```

---

## References

- `docs/risk_primitives.md` - Canonical primitives documentation
- `merid/event_venues/kalshi/fees.py` - Fee implementation
- `scripts/replay_harness.py` - Replay harness tool
- `scripts/surveillance_reconciliation.py` - Surveillance reconciliation tool
- `docs/alert_rules.md` - Alert rules
- `docs/dashboard_requirements.md` - Dashboard requirements
