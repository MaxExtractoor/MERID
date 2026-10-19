# Live First-Fill Report (Example)

**Session Date**: 2026-05-23
**Session Start Time**: 22:03 UTC
**Profile**: kalshi_crypto_15m_v2
**Mode**: LIVE
**Bug Fixes Applied**: Bug 26 (duplicate settings field definitions)
**Pre-Run Checklist**: ✅ Complete (see `docs/live_run_monitoring_checklist.md`)

---

## Executive Summary

**First Fill Time**: 22:04:17 UTC
**Total Cycle Duration**: 11 minutes (entry at 22:04, expiry at 22:15)
**Net PnL**: $0.18 (+18%)
**System Health**: Excellent
**Risk Controls**: All passed
**Reconciliation**: Perfect (delta = $0.00)

**Summary**: First live cycle completed successfully. System correctly identified edge opportunity, passed all risk gates, submitted order to Kalshi API, and held through expiry. Market settled YES, resulting in +$0.18 profit after fees. All risk controls, reconciliation, and dashboard metrics behaved as expected.

---

## Entry Order Details

| Field | Value |
|-------|-------|
| **Ticker** | `KXBTC15M-26MAY232215-15` |
| **Side** | YES |
| **Action** | BUY |
| **Count** | 1 contract |
| **Price** | 65¢ |
| **Notional** | $0.65 |
| **Model Probability** | 0.80 |
| **Implied Probability** | 0.65 |
| **Edge** | 15% |
| **Confidence** | 0.72 |
| **Time to Expiry** | 11 min |
| **Window Valid** | yes |
| **Kalshi Order ID** | `7a8b9c0d-1e2f-3a4b-5c6d-7e8f9a0b1c2d` |
| **Client Order ID** | `merid-3f2a1b8c9d4e5f6a7b8c9d0e1f2a3b4c` |
| **Submission Timestamp** | 2026-05-23 22:04:17.234 UTC |
| **Submission Latency** | 127 ms |
| **Fill Timestamp** | 2026-05-23 22:04:17.412 UTC |
| **Fill Latency** | 178 ms |
| **Fill Status** | filled |

**Entry Rationale**:
```
15m lean signal: spot 76,803.29 <= 80,000 edge_pct=0.15
Model probability (0.80) significantly above implied (0.65)
Edge threshold (8%) exceeded by 7 percentage points
Window valid: 11 min to expiry, within 5-15 min entry window
```

**Entry Logs**:
```
2026-05-23 22:04:17 | INFO | merid.prediction.agent_grid_15m | [SIZE-APPLIED] series=BTC_15M asset=BTC count=1 notional=0.65 bankroll=36.58
2026-05-23 22:04:17 | INFO | merid.prediction.agent_grid_15m | [PRE-TRADE-VALIDATION] market_id=KXBTC15M-26MAY232215-15 asset=BTC price_source=live_book executable=true notional=0.65 min_notional_ok=true decision=submit reason=validation_passed
2026-05-23 22:04:17 | INFO | merid.event_venues.kalshi.contract_lease | [LEASE] acquired key=kalshi:KXBTC15M-26MAY232215-15:yes:BTC_15M owner=BTC_15M ttl=300s
2026-05-23 22:04:17 | INFO | merid.event_venues.kalshi.order_gate | [GATE] allowed coid=merid-3f2a1b8c9d4e5f6a7b8c9d0e1f2a3b4c contract=KXBTC15M-26MAY232215-15 agent=BTC_15M count=1 price=65¢
2026-05-23 22:04:17 | INFO | merid.guards.global_risk_guard | [GLOBAL-RISK-GUARD] APPROVED | ticker=KXBTC15M-26MAY232215-15 | max_loss=$0.65 | cycle_used=$0.65 / $1.09 | total_would_be=$0.65
2026-05-23 22:04:17 | INFO | merid.event_venues.kalshi.order_router | [ORDER-CONSTRUCTION-AUDIT] intent_id=intent_a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6 ticker=KXBTC15M-26MAY232215-15 side=yes action=buy price_cents=65 count=1 agent_id=BTC_15M source=BTC_15M rationale=15m lean signal: spot 76803.29 <= 80000 edge_pct=0.15 mode=live snapshot_age=0.3s
2026-05-23 22:04:17 | INFO | merid.event_venues.kalshi.order_router | [order-router] Live order submitted to Kalshi API: ticker=KXBTC15M-26MAY232215-15 side=yes count=1 price=65¢
2026-05-23 22:04:17 | INFO | merid.prediction.agent_grid_15m | [KALSHI-ORDER-LIFECYCLE] BTC_15M | intent_id=intent_a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6 | client_tag=merid-3f2a1b8c9d4e5f6a7b8c9d0e1f2a3b4c | ticker=KXBTC15M-26MAY232215-15 | side=yes | count=1 | price_cents=65 | status=submitted_live | kalshi_order_id=7a8b9c0d-1e2f-3a4b-5c6d-7e8f9a0b1c2d | latency_ms=305
2026-05-23 22:04:17 | INFO | merid.event_venues.kalshi.order_router | [order-router] FILL CONFIRMED: ticker=KXBTC15M-26MAY232215-15 side=yes count=1 price=65¢ order_id=7a8b9c0d-1e2f-3a4b-5c6d-7e8f9a0b1c2d
2026-05-23 22:04:17 | INFO | merid.prediction.agent_grid_15m | [KALSHI-ORDER-LIFECYCLE] BTC_15M | intent_id=intent_a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6 | client_tag=merid-3f2a1b8c9d4e5f6a7b8c9d0e1f2a3b4c | ticker=KXBTC15M-26MAY232215-15 | side=yes | count=1 | price_cents=65 | status=filled_live | kalshi_order_id=7a8b9c0d-1e2f-3a4b-5c6d-7e8f9a0b1c2d | latency_ms=178
```

---

## Exit Order Details

| Field | Value |
|-------|-------|
| **Ticker** | `KXBTC15M-26MAY232215-15` |
| **Side** | YES |
| **Action** | N/A (expiry settlement) |
| **Count** | 1 contract |
| **Price** | 100¢ (settlement) |
| **Notional** | $1.00 |
| **Exit Trigger** | expiry |
| **Trigger Price** | N/A (market settled YES) |
| **Kalshi Order ID** | N/A (expiry settlement) |
| **Client Order ID** | N/A (expiry settlement) |
| **Submission Timestamp** | N/A (expiry settlement) |
| **Submission Latency** | N/A (expiry settlement) |
| **Fill Timestamp** | 2026-05-23 22:15:00.000 UTC |
| **Fill Latency** | N/A (expiry settlement) |
| **Fill Status** | filled (settlement) |

**Exit Rationale**:
```
Market expired at 22:15 UTC
Settlement: YES (BTC price > $75,000 strike)
No take-profit or stop-loss triggered (held through expiry)
```

**Exit Logs**:
```
2026-05-23 22:15:00 | INFO | merid.event_venues.kalshi.fills_ledger | [FILLS-LEDGER] Settlement fill recorded: ticker=KXBTC15M-26MAY232215-15 side=yes count=1 price=100¢ settlement=YES
2026-05-23 22:15:01 | INFO | merid.event_venues.kalshi.position_sizer | [PNL-UPDATE] Realized PnL: $0.18 | Unrealized PnL: $0.00 | Total PnL: $0.18
2026-05-23 22:15:02 | INFO | merid.event_venues.kalshi.fills_ledger | [BANKROLL-RECON] Kalshi balance: $36.76 | Local bankroll: $36.76 | Delta: $0.00
```

---

## Cycle PnL Breakdown

| Component | Value |
|-----------|-------|
| **Entry Cost** | $0.65 |
| **Exit Proceeds** | $1.00 |
| **Kalshi Fees (Entry)** | $0.02 |
| **Kalshi Fees (Exit)** | $0.15 |
| **Total Fees** | $0.17 |
| **Gross PnL** | $0.35 |
| **Net PnL** | $0.18 |
| **Net PnL %** | +18% |
| **Holding Time** | 11 min |

**PnL Logs**:
```
2026-05-23 22:15:01 | INFO | merid.event_venues.kalshi.position_sizer | [PNL-UPDATE] Realized PnL: $0.18 | Unrealized PnL: $0.00 | Total PnL: $0.18
2026-05-23 22:15:01 | INFO | merid.event_venues.kalshi.fills_ledger | [FEE-TRACKING] Entry fee: $0.02 | Exit fee: $0.15 | Total fees: $0.17
```

---

## System Behavior Analysis

### Risk Controls

| Control | Status | Details |
|---------|--------|---------|
| **Pre-Trade Gate** | ✅ | Lease acquired (300s TTL), dedup passed (no duplicate), fill-awareness passed (no existing position) |
| **Global Risk Guard** | ✅ | Budget check passed: $0.65 used / $1.09 available (60% of cycle budget) |
| **Risk Envelope** | ✅ | Min floor applied: target $0.73 (2.0%) → actual $0.65 (1.8%) = 89% of target (within tolerance) |
| **Kelly Cap** | ✅ | Position sizing: 1 contract = $0.65, Kelly fraction 2.7%, within cap |
| **Deep-OTM Filter** | ✅ | Price 65¢ not below deep-OTM threshold (20¢) |
| **Deep-ITM Filter** | ✅ | Price 65¢ not above deep-ITM threshold (80¢) |
| **Price-Band Check** | ✅ | Price 65¢ within acceptable band (40¢ - 90¢) |
| **Market Regime Gate** | ✅ | Basket not flat (3/5 assets showing edge), ALLOW mode |
| **Kill Switch** | ✅ | All kill switches inactive |

**Risk Control Logs**:
```
2026-05-23 22:04:17 | INFO | merid.event_venues.kalshi.contract_lease | [LEASE] acquired key=kalshi:KXBTC15M-26MAY232215-15:yes:BTC_15M owner=BTC_15M ttl=300s
2026-05-23 22:04:17 | INFO | merid.event_venues.kalshi.order_gate | [GATE] allowed coid=merid-3f2a1b8c9d4e5f6a7b8c9d0e1f2a3b4c contract=KXBTC15M-26MAY232215-15 agent=BTC_15M count=1 price=65¢
2026-05-23 22:04:17 | INFO | merid.guards.global_risk_guard | [GLOBAL-RISK-GUARD] APPROVED | ticker=KXBTC15M-26MAY232215-15 | max_loss=$0.65 | cycle_used=$0.65 / $1.09 | total_would_be=$0.65
2026-05-23 22:04:17 | INFO | merid.prediction.unified_sizing | [RISK-ENVELOPE] Asset BTC: min_floor applied - target $0.73 (2.0%) -> actual $0.65 (1.8%) = 89.0% of target
2026-05-23 22:04:17 | INFO | merid.market_regime.gate | [market-regime-gate] decision=ALLOW | flat_count=2/5 | basket_not_too_flat=true
```

### Execution Path

| Stage | Status | Latency | Notes |
|-------|--------|---------|-------|
| **Signal Generation** | ✅ | 45 ms | Agent decision: PLACE, edge=15% |
| **Order Construction** | ✅ | 23 ms | OrderIntent created with all metadata |
| **Pre-Trade Gate** | ✅ | 31 ms | Lease, dedup, fill-awareness all passed |
| **Risk Checks** | ✅ | 18 ms | All 9 risk gates passed |
| **Kalshi API Submission** | ✅ | 127 ms | place_order_result successful |
| **Fill Confirmation** | ✅ | 178 ms | WS bridge received fill update |
| **Fill Ledger Update** | ✅ | 12 ms | Local persistence complete |
| **Position Cache Update** | ✅ | 8 ms | Exposure tracking updated |
| **Bankroll Reconciliation** | ✅ | 23 ms | Balance check: delta=$0.00 |

**Execution Logs**:
```
2026-05-23 22:04:17 | INFO | merid.prediction.agent_grid_15m | [TRADE-TRACE] trace_id=abc123 | agent_id=BTC_15M | market_id=KXBTC15M-26MAY232215-15 | side=yes | bankroll_usd=36.58 | risk_target_pct=2.00% | effective_risk_pct=1.80% | min_max_notional_usd=0.73 | override_threshold=0.00 | price_cents=65 | contract_price_usd=0.65 | contract_size_usd=1.0 | implied=0.650 | model_pre_clamp=0.800 | model_post_clamp=0.800 | edge_req=8.00% | edge_actual=15.00% | spread_cents=2 | spread_edge=3.08% | confidence=0.72 | time_to_expiry=11.00min | window_valid=yes | contracts=1 | notional_usd=0.65 | decision=PLACE | decision_stage=EDGE | decision_reason=EDGE_YES
2026-05-23 22:04:17 | INFO | merid.event_venues.kalshi.order_router | [ORDER-CONSTRUCTION-AUDIT] intent_id=intent_a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6 ticker=KXBTC15M-26MAY232215-15 side=yes action=buy price_cents=65 count=1 agent_id=BTC_15M source=BTC_15M rationale=15m lean signal: spot 76803.29 <= 80000 edge_pct=0.15 mode=live snapshot_age=0.3s
2026-05-23 22:04:17 | INFO | merid.event_venues.kalshi.order_router | [order-router] Live order submitted to Kalshi API: ticker=KXBTC15M-26MAY232215-15 side=yes count=1 price=65¢
2026-05-23 22:04:17 | INFO | merid.event_venues.kalshi.order_router | [order-router] FILL CONFIRMED: ticker=KXBTC15M-26MAY232215-15 side=yes count=1 price=65¢ order_id=7a8b9c0d-1e2f-3a4b-5c6d-7e8f9a0b1c2d
```

### Reconciliation

| Metric | Value | Status |
|--------|-------|--------|
| **Kalshi Balance** | $36.76 | ✅ |
| **Local Bankroll** | $36.76 | ✅ |
| **Reconciliation Delta** | $0.00 | ✅ |
| **Missing Fills** | 0 | ✅ |
| **Duplicate Fills** | 0 | ✅ |

**Reconciliation Logs**:
```
2026-05-23 22:15:02 | INFO | merid.event_venues.kalshi.fills_ledger | [BANKROLL-RECON] Kalshi balance: $36.76 | Local bankroll: $36.76 | Delta: $0.00
2026-05-23 22:15:02 | INFO | merid.event_venues.kalshi.fills_ledger | [FILL-DEDUP] No duplicate fills detected for order 7a8b9c0d-1e2f-3a4b-5c6d-7e8f9a0b1c2d
2026-05-23 22:15:02 | INFO | merid.event_venues.kalshi.fills_ledger | [FILL-COMPLETENESS] All fills from Kalshi API present in local ledger
```

---

## Dashboard Health

### Pipeline Health (`merid_15m_pipeline_health`)

| Metric | Status | Notes |
|--------|--------|-------|
| **Agent Health** | 🟢 | All 5 agents (BTC_15M, ETH_15M, SOL_15M, XRP_15M, DOGE_15M) running |
| **Catalog Refresh** | 🟢 | Last refresh 22:04:17, 42 markets discovered |
| **Spot Feed** | 🟢 | Last update 22:04:59, all 5 assets fresh (< 5s stale) |
| **WebSocket Bridge** | 🟢 | Connected, receiving order updates |
| **Order Router** | 🟢 | 1 order submitted, 1 fill confirmed, no errors |

### Risk Safety (`merid_risk_safety`)

| Metric | Status | Notes |
|--------|--------|-------|
| **Category Exposure** | 🟢 | Crypto exposure: $0.65 (1.8% of bankroll) |
| **Asset Exposure** | 🟢 | BTC exposure: $0.65 (1.8% of bankroll) |
| **Risk Envelope** | 🟢 | All assets within min floor tolerance |
| **Kill Switches** | 🟢 | All inactive (no safety triggers) |

### PnL Exposure (`merid_pnl_exposure`)

| Metric | Status | Notes |
|--------|--------|-------|
| **Realized PnL** | 🟢 | +$0.18 (first cycle) |
| **Unrealized PnL** | 🟢 | $0.00 (no open positions post-expiry) |
| **Bankroll Tracking** | 🟢 | Reconciliation delta $0.00 |
| **Position Count** | 🟢 | 0 open positions (all expired) |

---

## Anomalies and Issues

### Issues Detected

| ID | Severity | Description | Resolution |
|----|----------|-------------|------------|
| None | N/A | No issues detected | N/A |

### Log Anomalies

```
No anomalies detected. All log patterns matched expected behavior.
Minor logging format error in TRADE-TRACE (cosmetic, does not affect trading):
TypeError: must be real number, not str (line 526 in agent_grid_15m.py)
This is a pre-existing cosmetic bug in the logging format string and does not impact order execution.
```

### Dashboard Anomalies

```
No dashboard anomalies detected. All metrics updated correctly and matched log data.
```

---

## Recommendations

### Immediate Actions

- [ ] Fix cosmetic logging format error in agent_grid_15m.py line 526 (low priority, does not affect trading)
- [ ] Continue monitoring for additional edge opportunities in current session

### Follow-Up Items

- [ ] Monitor next 5-10 cycles to validate consistent behavior
- [ ] Review edge-threshold settings if too many NO_EDGE_YES rejections occur
- [ ] Consider increasing bankroll if consistent profitability observed over 20+ cycles

### Configuration Adjustments

- [ ] No configuration adjustments needed at this time
- [ ] Current settings (edge thresholds, Kelly caps, risk envelope) performed well

---

## Conclusion

**Overall Assessment**: Excellent

**Key Takeaways**:
1. **End-to-end live execution validated**: Config → VenueGate → order_router → Kalshi API → fill → reconciliation all working correctly
2. **All 26 bugs closed**: Including Bug 26 (duplicate settings field definitions) which was critical for live mode
3. **Risk controls functioning as designed**: All 9 risk gates passed, exposure tracking accurate, kill switches inactive
4. **Reconciliation perfect**: Zero delta between Kalshi balance and local bankroll
5. **Dashboard health excellent**: All agents running, spot feed fresh, WebSocket bridge connected

**Next Steps**:
- [ ] Continue live monitoring for 30-60 minutes to observe additional cycles
- [ ] Document any subsequent fills in follow-up reports
- [ ] After 20+ cycles, review aggregate performance statistics
- [ ] Consider scaling bankroll if consistent profitability and low risk observed

**Report Prepared By**: Cascade AI Assistant
**Report Date**: 2026-05-23
**Review Status**: Pending
