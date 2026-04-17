# Incident Example 4: Compound Failure — WS Hiccup + Kill Switch Race + Synthetic Leakage

> **Severity:** CRITICAL  
> **Profile:** `kalshi-only` (LIVE)  
> **Detection Time:** 2 minutes  
> **Resolution Time:** 8 minutes  

---

## Executive Summary

A WebSocket latency spike caused a batch of fills to arrive out-of-order, triggering a temporary reconciliation break. While the system was in this degraded state, the risk engine tripped the kill switch based on stale exposure data. Concurrently, a synthetic "what-if" router (misconfigured during a hotfix) wrote orders into the live lineage stream without the `synthetic=True` flag, causing synthetic orders to appear in the LIVE positions view.

**The compound nature of these failures** meant that operators saw:
1. A reconciliation break alert (red)
2. Kill switch trip (red)
3. New "positions" appearing despite kill switch being active (confusion)
4. Some positions labeled "synthetic" while others weren't (mixed state)

---

## Timeline (T+0 to T+12s)

| Time | Event | Order ID | Component | State |
|------|-------|----------|-----------|-------|
| T+0 | Order placed via live router | `ord_kxbtc_2026_001` | `kalshi_api.py` | `submitted` |
| T+0.2 | Fill recorded at Kalshi | `fill_kalshi_001` | Kalshi WS | `filled` |
| T+0.3 | **WS latency spike begins** | — | WebSocket | — |
| T+0.8 | Second fill recorded | `fill_kalshi_002` | Kalshi WS | `filled` |
| T+1.5 | Fill batch arrives out-of-order | — | `kalshi_api.py` | `reconciling` |
| T+2.0 | Position shows 0 contracts despite 2 fills | `pos_kxbtc` | Position Cache | **BROKEN** |
| T+2.2 | Reconciliation status: `degraded` | — | Reconciliation | `degraded` |
| T+2.5 | Risk engine polls stale position (0 contracts) | — | `kalshi_risk.py` | — |
| T+2.6 | Risk computes exposure using cached PnL | — | `kalshi_risk.py` | — |
| T+2.8 | **Kill switch trips** (false positive) | — | Kill Switch | `active` |
| T+3.0 | Synthetic router (hotfix) places "what-if" order | `ord_synth_001` | Synthetic Router | **MISFLAGGED** |
| T+3.2 | Synthetic order enters lineage without `synthetic=True` | `ord_synth_001` | Lineage Store | **LEAKED** |
| T+3.5 | UI fetches positions, sees mixed data | — | KalshiDashboard | **MIXED** |
| T+4.0 | Operator sees: killswitch=on, new position appeared | — | UI | **CONFUSION** |
| T+5.0 | Synthetic flag check in profile guard **FAILS** | — | Profile Guard | **ALERT** |
| T+6.0 | Operator runs incident replay | `ord_kxbtc_2026_001` | Incident Replay | `investigating` |
| T+8.0 | Root cause identified | — | Operator | — |
| T+10.0 | Kill switch reset (after manual verification) | — | Operator | `cleared` |
| T+12.0 | Synthetic orders quarantined, reconciliation repaired | — | System | `resolved` |

---

## Detection: Which Guard Caught This?

| Guard/Invariant | Detection Point | Alert/Action |
|---------------|-----------------|--------------|
| **Reconciliation Status** | T+2.2 | `/api/v1/kalshi/reconciliation/status` returns `degraded` |
| **Profile Guard** | T+5.0 | `test_profile_guard_live_mode.py::test_live_mode_no_synthetic_orders_unflagged` **FAILS** |
| **Kill Switch Invariant** | T+2.8 | `test_chaos_compound_failures.py` would catch: kill switch tripped during fill ingestion |
| **Lineage Completeness** | T+6.0 | Incident replay shows `ord_synth_001` missing `external_venue` and `synthetic` flags |
| **CI Red-Team Lane** | Nightly | `fuzz_replay` job would flag `ord_synth_001` as synthetic leaking to LIVE |

---

## Investigation Commands

```bash
# 1. Check current reconciliation status
curl http://localhost:8000/api/v1/kalshi/reconciliation/status | jq .

# 2. Run incident replay on the affected order
python scripts/incident_replay.py ord_kxbtc_2026_001 \
    --start-time 2026-03-24T10:00:00Z \
    --end-time 2026-03-24T10:01:00Z \
    --format markdown

# 3. Check kill switch state transitions
python scripts/incident_replay.py ord_kxbtc_2026_001 --format timeline | grep -i "kill"

# 4. Verify data source badges for all active orders
curl http://localhost:8000/api/v1/kalshi/positions | jq '.positions[] | {ticker, synthetic, manual_or_external}'

# 5. Check synthetic router logs (if applicable)
grep "synthetic" /var/log/merid/kalshi_router.log | tail -20
```

---

## Root Cause Analysis

### 1. WebSocket Latency Spike (Trigger)
- **Cause:** Network partition between Kalshi WS and MERID ingestion
- **Impact:** Fill batch arrived out-of-order (fill_002 before fill_001)
- **Why reconciliation broke:** Position cache applied fills in arrival order, not logical order

### 2. Stale Exposure Kill Switch Trip (Cascade)
- **Cause:** Risk engine polled position cache during reconciliation repair
- **Impact:** Saw 0 contracts when 2 fills were pending, computed incorrect exposure
- **Why kill switch tripped:** Exposure calculation used stale data, triggered `max_daily_loss` threshold

### 3. Synthetic Order Leakage (Compounder)
- **Cause:** Hotfix to synthetic "what-if" router omitted `synthetic=True` flag
- **Impact:** Synthetic orders appeared as live orders in positions view
- **Why profile guard caught it:** `test_live_mode_all_orders_have_explicit_flags` asserted missing `synthetic` field

---

## Resolution

### Immediate (Operator Actions)

1. **Verify no real money at risk:**
   ```bash
   python scripts/incident_replay.py ord_kxbtc_2026_001 --format json | jq '.fills | length'
   # Result: 2 fills from live Kalshi venue
   ```

2. **Quarantine synthetic orders:**
   ```bash
   # Flag all orders missing explicit badges as external
   curl -X POST http://localhost:8000/api/v1/admin/quarantine \
     -d '{"order_ids": ["ord_synth_001"], "reason": "missing_synthetic_flag"}'
   ```

3. **Reset kill switch after verification:**
   ```bash
   curl -X POST http://localhost:8000/api/v1/system/kill-switch/reset \
     -d '{"operator": "incident-4", "reason": "stale_data_false_positive"}'
   ```

### System Fixes (Post-Incident)

| Fix | Location | Status |
|-----|----------|--------|
| Event-driven kill switch (no polling) | `kalshi_risk.py` | ✅ Merged |
| Reconciliation status blocks risk calc | `kalshi_risk.py:record_rate_only()` | ✅ Merged |
| Synthetic router profile guard | `kalshi_api.py` | ✅ Merged |
| Out-of-order fill ingestion | `position_cache.py` | ✅ Merged |
| WS reconnection backoff | `kalshi/ws_bridge.py` | ✅ Merged |

---

## Lessons Learned

### What Went Wrong
1. **Tight coupling:** Risk engine didn't check reconciliation status before computing exposure
2. **Implicit defaults:** Synthetic router relied on default `synthetic=False` instead of explicit flag
3. **Ordering assumptions:** Fill ingestion assumed monotonic arrival (it shouldn't)

### What Went Right
1. **Profile guards caught the synthetic leakage** within 5 seconds of it appearing
2. **Reconciliation status was exposed** immediately, allowing operators to diagnose
3. **Incident replay provided full timeline** in under 2 minutes of investigation
4. **CI invariants would have prevented the synthetic flag omission** if run pre-deploy

### Invariant Violations Detected

| Invariant | Violation | Detection |
|-----------|-----------|-----------|
| `position_size_equals_fill_sum` | Position showed 0, 2 fills existed | Reconciliation check |
| `no_unbacked_live_positions` | Synthetic order appeared as live | Profile guard |
| `kill_switch_monotonic` | Kill switch tripped during ingestion | Chaos test |
| `explicit_flags_required` | `synthetic` flag missing | Profile guard |
| `mixed_mode_requires_banner` | UI showed MIXED without banner | UI test |

---

## Reproducible Test Case

```python
# tests/test_chaos_compound_failures.py
# This compound failure is now tested in CI

class TestCompoundFailureScenario:
    """
    Reproduces the WS hiccup + kill switch race + synthetic leakage
    from Incident Example 4.
    """
    
    def test_compound_ws_delay_kill_switch_synthetic(self):
        # Arrange: Live profile, 2 fills pending
        profile = "kalshi-only"
        fills = [fill_001, fill_002]  # Out of order arrival
        
        # Act: Delay fills, trip kill switch, inject misflagged synthetic
        with ws_delay(500):  # 500ms latency
            ingest_fills(fills)  # Out of order
            trip_kill_switch("stale_exposure")
            place_synthetic_order(flags={})  # Missing synthetic=True
        
        # Assert: Profile guard catches synthetic
        assert_profile_guard_fails("live_mode_no_synthetic_orders_unflagged")
        
        # Assert: No live positions remain after kill switch
        assert_no_live_orders_after_kill_switch()
        
        # Assert: Reconciliation eventually recovers
        assert_eventually(lambda: reconciliation_status() == "ok")
```

---

## Related Incidents

- [Example 1: Incomplete Lineage](example_1_incomplete_lineage.md) — Ghost order from migration
- [Example 2: Reconciliation Break](example_2_reconciliation_break.md) — Unmatched fill from network timeout
- [Example 3: Kill Switch Race](example_3_kill_switch_race.md) — 800ms window between check and place

---

## Runbook References

- [Incident Investigation Runbook](../INCIDENT_INVESTIGATION_RUNBOOK.md)
- [MERID Trading Data Contracts](../MERID_TRADING_DATA_CONTRACTS.md)
- [Profile Guard Tests](../../../tests/test_profile_guard_live_mode.py)
- [Chaos Compound Failures](../../../tests/test_chaos_compound_failures.py)

---

*Last updated: 2026-03-24*  
*Document version: 1.0*
