# Incident Timeline Example: Synthetic Order Leak
## Date: 2026-03-20 14:32 UTC
## Severity: CRITICAL
## ID: INC-2026-0320-001

---

## Summary
A synthetic backtest order leaked into live production execution, resulting in 50 contracts of KXBTC-15M being executed with live capital despite being generated from simulation data.

## Detection
- **14:30:15 UTC** — Kill switch auto-triggers due to unexpected position delta
- **14:31:00 UTC** — Operator notices "synthetic" flag in order lineage but live fills
- **14:32:00 UTC** — `incident_replay.py` investigation initiated

## Investigation (using incident_replay.py)

```bash
python scripts/incident_replay.py ord_kxbtc_sim_001 \
    --start-time 2026-03-20T14:25:00Z \
    --end-time 2026-03-20T14:35:00Z \
    --format runbook
```

### Output Summary

**Severity:** CRITICAL  
**Data Source:** SYNTHETIC (leaked to live)  
**Lineage:** COMPLETE (but synthetic flag ignored downstream)

## Timeline

| Time | Event | Data Source |
|------|-------|-------------|
| 14:25:00 | Backtest harness generates signal | SYNTHETIC |
| 14:25:05 | Signal stored in Redis with `is_synthetic=true` | SYNTHETIC |
| 14:28:30 | AgentGrid polls signal (sees `is_synthetic=true`) | SYNTHETIC |
| 14:28:35 | **BUG:** OrderRouter skips synthetic check in "fast path" | **LIVE LEAK** |
| 14:28:36 | Order submitted to Kalshi API | LIVE |
| 14:28:37 | Kalshi accepts order | LIVE |
| 14:29:15 | Fill received: 50 contracts @ 55¢ | LIVE |
| 14:30:15 | Position delta triggers kill switch | LIVE |

## Root Cause

**Shadow Path Bug:** The `OrderRouter._submit_fast()` method (added for latency optimization) bypassed the `is_synthetic` flag check that exists in the normal `_submit()` path.

```python
# Bug in order_router.py:submit_fast()
async def submit_fast(self, order):
    # Missing: if order.is_synthetic: raise SyntheticOrderError()
    return await self.kalshi_client.create_order(order)  # Leaked!
```

## Resolution Steps

1. ✅ **Immediate (14:35 UTC):** Kill switch engaged, no further orders
2. ✅ **Immediate (14:40 UTC):** Position flattened via manual hedging
3. ✅ **Fix (15:00 UTC):** Added synthetic check to `submit_fast()`
4. ✅ **Fix (15:15 UTC):** Added property-based test for synthetic invariants
5. ✅ **Deploy (16:00 UTC):** Hotfix deployed to production

## Lessons Learned

### What Worked
- Kill switch detected position anomaly within 2 minutes
- Lineage tracing immediately identified synthetic flag
- `incident_replay.py` generated complete timeline in <5 min

### What Failed
- Shadow path (`submit_fast`) lacked synthetic checks
- No property-based test for "synthetic orders never hit live"
- CI did not catch the bypass due to direct client usage

## Prevention

1. **Property Test Added:** `test_api_never_leaks_synthetic_without_flag`
2. **CI Guard:** Shadow-path detector now greps for direct client calls
3. **Runbook Update:** This example added to on-call training

## Replay Command

```bash
# Reproduce this investigation
python scripts/incident_replay.py ord_kxbtc_sim_001 \
    --start-time 2026-03-20T14:25:00Z \
    --end-time 2026-03-20T14:35:00Z \
    --format markdown \
    --output docs/incident_examples/synthetic_leak_2026-03-20.md
```

## Artifacts

- **Lineage:** `/api/v1/kalshi/orders/ord_kxbtc_sim_001/lineage`
- **Reconciliation:** `/api/v1/kalshi/reconciliation/breaks`
- **Kill Switch Log:** `/api/v1/observability/state-transitions?component=kill_switch`
- **Fix PR:** #1847 (OrderRouter synthetic guard)
