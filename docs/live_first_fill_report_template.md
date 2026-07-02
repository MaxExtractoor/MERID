# Live First-Fill Report

**Session Date**: 2026-05-23
**Session Start Time**: 22:03 UTC
**Session End Time**: [TBD]
**Profile**: kalshi_crypto_15m_v2
**Profile Version**: [TBD - add version field to profile]
**Mode**: LIVE
**Bug Fixes Applied**: Bug 26 (duplicate settings field definitions), Bug 27 (TRADE-TRACE logging), Bug 28 (maker-taker attribute), Bug 29 (risk envelope)
**Pre-Run Checklist**: ✅ Complete (see `docs/live_run_monitoring_checklist.md`)
**Run ID**: [TBD - auto-generated UUID]

---

## Executive Summary

**First Fill Time**: [TBD]
**Total Cycle Duration**: [TBD]
**Total Cycles**: [TBD]
**Total Orders Submitted**: [TBD]
**Total Fills**: [TBD]
**Fill Rate**: [TBD]%
**Net PnL**: $[TBD] ([TBD]%)
**Max Drawdown**: [TBD]%
**System Health**: [TBD]
**Risk Controls**: [TBD]
**Reconciliation**: [TBD]

---

## Pre-Run Snapshot

| Metric | Value |
|--------|-------|
| **Bankroll (Start)** | $[TBD] |
| **Kelly Fraction** | [TBD] |
| **Max Drawdown (Start)** | [TBD]% |
| **BTC Exposure** | $[TBD] ([TBD]%) |
| **ETH Exposure** | $[TBD] ([TBD]%) |
| **SOL Exposure** | $[TBD] ([TBD]%) |
| **XRP Exposure** | $[TBD] ([TBD]%) |
| **DOGE Exposure** | $[TBD] ([TBD]%) |
| **Total Crypto Exposure** | $[TBD] ([TBD]%) |
| **Open Positions** | [TBD] |
| **Pending Orders** | [TBD] |

**Snapshot Timestamp**: [TBD]
**Snapshot Source**: [Kalshi API / Local Cache]

---

## Post-Run Snapshot

| Metric | Value | Delta |
|--------|-------|-------|
| **Bankroll (End)** | $[TBD] | $[TBD] |
| **Kelly Fraction** | [TBD] | [TBD] |
| **Max Drawdown (End)** | [TBD]% | [TBD]% |
| **BTC Exposure** | $[TBD] ([TBD]%) | $[TBD] |
| **ETH Exposure** | $[TBD] ([TBD]%) | $[TBD] |
| **SOL Exposure** | $[TBD] ([TBD]%) | $[TBD] |
| **XRP Exposure** | $[TBD] ([TBD]%) | $[TBD] |
| **DOGE Exposure** | $[TBD] ([TBD]%) | $[TBD] |
| **Total Crypto Exposure** | $[TBD] ([TBD]%) | $[TBD] |
| **Open Positions** | [TBD] | [TBD] |
| **Pending Orders** | [TBD] | [TBD] |

**Snapshot Timestamp**: [TBD]
**Snapshot Source**: [Kalshi API / Local Cache]

---

## Entry Order Details

| Field | Value |
|-------|-------|
| **Ticker** | `KX____-26MAY____-15` |
| **Side** | YES / NO |
| **Action** | BUY / SELL |
| **Count** | ___ contracts |
| **Price** | ___¢ |
| **Notional** | $___ |
| **Model Probability** | ___ |
| **Implied Probability** | ___ |
| **Edge** | ___% |
| **Confidence** | ___ |
| **Time to Expiry** | ___ min |
| **Window Valid** | yes / no |
| **Kalshi Order ID** | `_____` |
| **Client Order ID** | `merid-_____` |
| **Submission Timestamp** | [TBD] |
| **Submission Latency** | ___ ms |
| **Fill Timestamp** | [TBD] |
| **Fill Latency** | ___ ms |
| **Fill Status** | filled / partial / rejected |

**Entry Rationale**:
```
[TBD - copy from logs or agent rationale]
```

**Entry Logs**:
```
[TBD - paste relevant log snippets]
```

---

## Exit Order Details

| Field | Value |
|-------|-------|
| **Ticker** | `KX____-26MAY____-15` |
| **Side** | YES / NO |
| **Action** | BUY / SELL |
| **Count** | ___ contracts |
| **Price** | ___¢ |
| **Notional** | $___ |
| **Exit Trigger** | take-profit / stop-loss / expiry / manual |
| **Trigger Price** | ___¢ |
| **Kalshi Order ID** | `_____` |
| **Client Order ID** | `merid-_____` |
| **Submission Timestamp** | [TBD] |
| **Submission Latency** | ___ ms |
| **Fill Timestamp** | [TBD] |
| **Fill Latency** | ___ ms |
| **Fill Status** | filled / partial / rejected |

**Exit Rationale**:
```
[TBD - copy from logs or agent rationale]
```

**Exit Logs**:
```
[TBD - paste relevant log snippets]
```

---

## Cycle PnL Breakdown

| Component | Value |
|-----------|-------|
| **Entry Cost** | $___ |
| **Exit Proceeds** | $___ |
| **Kalshi Fees (Entry)** | $___ |
| **Kalshi Fees (Exit)** | $___ |
| **Total Fees** | $___ |
| **Gross PnL** | $___ |
| **Net PnL** | $___ |
| **Net PnL %** | ___% |
| **Holding Time** | ___ min |

**PnL Logs**:
```
[TBD - paste relevant log snippets]
```

---

## System Behavior Analysis

### Risk Controls

| Control | Status | Details |
|---------|--------|---------|
| **Pre-Trade Gate** | ✅ / ⚠️ / ❌ | [Lease, dedup, fill-awareness] |
| **Global Risk Guard** | ✅ / ⚠️ / ❌ | [Budget check] |
| **Risk Envelope** | ✅ / ⚠️ / ❌ | [Min floor applied] |
| **Kelly Cap** | ✅ / ⚠️ / ❌ | [Position sizing] |
| **Deep-OTM Filter** | ✅ / ⚠️ / ❌ | [Threshold check] |
| **Deep-ITM Filter** | ✅ / ⚠️ / ❌ | [Threshold check] |
| **Price-Band Check** | ✅ / ⚠️ / ❌ | [Range validation] |
| **Market Regime Gate** | ✅ / ⚠️ / ❌ | [Basket flatness] |
| **Kill Switch** | ✅ / ⚠️ / ❌ | [Safety trigger] |

**Risk Control Logs**:
```
[TBD - paste relevant log snippets]
```

### Execution Path

| Stage | Status | Latency | Notes |
|-------|--------|---------|-------|
| **Signal Generation** | ✅ | ___ ms | [Agent decision] |
| **Order Construction** | ✅ | ___ ms | [OrderIntent creation] |
| **Pre-Trade Gate** | ✅ | ___ ms | [Lease, dedup, fill-awareness] |
| **Risk Checks** | ✅ | ___ ms | [All risk gates] |
| **Kalshi API Submission** | ✅ | ___ ms | [place_order_result] |
| **Fill Confirmation** | ✅ | ___ ms | [WS bridge / poll] |
| **Fill Ledger Update** | ✅ | ___ ms | [Local persistence] |
| **Position Cache Update** | ✅ | ___ ms | [Exposure tracking] |
| **Bankroll Reconciliation** | ✅ | ___ ms | [Balance check] |

**Execution Logs**:
```
[TBD - paste relevant log snippets]
```

### Reconciliation

| Metric | Value | Status |
|--------|-------|--------|
| **Kalshi Balance** | $___ | ✅ / ⚠️ / ❌ |
| **Local Bankroll** | $___ | ✅ / ⚠️ / ❌ |
| **Reconciliation Delta** | $___ | ✅ / ⚠️ / ❌ |
| **Missing Fills** | ___ | ✅ / ⚠️ / ❌ |
| **Duplicate Fills** | ___ | ✅ / ⚠️ / ❌ |

**Reconciliation Logs**:
```
[TBD - paste relevant log snippets]
```

---

## Dashboard Health

### Pipeline Health (`merid_15m_pipeline_health`)

| Metric | Status | Notes |
|--------|--------|-------|
| **Agent Health** | 🟢 / 🟡 / 🔴 | [All 5 agents running] |
| **Catalog Refresh** | 🟢 / 🟡 / 🔴 | [Market discovery] |
| **Spot Feed** | 🟢 / 🟡 / 🔴 | [Price data freshness] |
| **WebSocket Bridge** | 🟢 / 🟡 / 🔴 | [Order updates] |
| **Order Router** | 🟢 / 🟡 / 🔴 | [Order routing health] |

### Risk Safety (`merid_risk_safety`)

| Metric | Status | Notes |
|--------|--------|-------|
| **Category Exposure** | 🟢 / 🟡 / 🔴 | [Crypto exposure %] |
| **Asset Exposure** | 🟢 / 🟡 / 🔴 | [Per-asset exposure] |
| **Risk Envelope** | 🟢 / 🟡 / 🔴 | [Min floor compliance] |
| **Kill Switches** | 🟢 / 🟡 / 🔴 | [All inactive] |

### PnL Exposure (`merid_pnl_exposure`)

| Metric | Status | Notes |
|--------|--------|-------|
| **Realized PnL** | 🟢 / 🟡 / 🔴 | [$___] |
| **Unrealized PnL** | 🟢 / 🟡 / 🔴 | [$___] |
| **Bankroll Tracking** | 🟢 / 🟡 / 🔴 | [Reconciliation delta] |
| **Position Count** | 🟢 / 🟡 / 🔴 | [Open positions] |

---

## Anomalies and Issues

### Issues Detected

| ID | Severity | Description | Resolution |
|----|----------|-------------|------------|
| [TBD] | P0 / P1 / P2 / P3 | [Description] | [Open / Resolved] |

### Log Anomalies

```
[TBD - paste any unexpected log messages or errors]
```

### Dashboard Anomalies

```
[TBD - describe any dashboard metrics that don't match expectations]
```

---

## Recommendations

### Immediate Actions

- [ ] [TBD - any immediate actions required]

### Follow-Up Items

- [ ] [TBD - any items to investigate post-session]

### Configuration Adjustments

- [ ] [TBD - any config tweaks based on observed behavior]

---

## Conclusion

**Overall Assessment**: [Excellent / Good / Fair / Poor]

**Key Takeaways**:
1. [TBD]
2. [TBD]
3. [TBD]

**Next Steps**:
- [ ] Continue live monitoring for [X] hours
- [ ] Adjust [config parameter] based on observed behavior
- [ ] Investigate [anomaly] in follow-up session

**Report Prepared By**: Cascade AI Assistant
**Report Date**: [TBD]
**Review Status**: Pending / Reviewed
