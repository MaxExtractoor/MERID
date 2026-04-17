# Incident Timeline Example: Kill Switch During High-Volume Execution
## Date: 2026-03-22 09:15 UTC
## Severity: HIGH
## ID: INC-2026-0322-002

---

## Summary
Kill switch triggered during a high-volume execution window, resulting in partial fills and a "zombie" position state. The incident exposed a race condition between kill-switch activation and in-flight orders.

## Detection
- **09:12:00 UTC** — Daily loss limit ($500) reached due to volatile market
- **09:12:01 UTC** — Kill switch activates
- **09:15:00 UTC** — Operator notices position shows "open" but "untradable"

## Investigation

```bash
python scripts/incident_replay.py ord_kxeth_003 \
    --start-time 2026-03-22T09:10:00Z \
    --end-time 2026-03-22T09:20:00Z \
    --format runbook
```

### Output Summary

**Severity:** HIGH  
**Data Source:** LIVE  
**Kill Switch:** ACTIVE during partial fill window  
**Lineage:** COMPLETE (but missing kill-switch state in order decision)

## Timeline

| Time | Event | Kill Switch | PnL Impact |
|------|-------|-------------|------------|
| 09:00:00 | Market opens with high volatility | inactive | — |
| 09:05:23 | First loss: -$120 | inactive | -$120 |
| 09:08:45 | Second loss: -$180 | inactive | -$300 |
| 09:10:12 | Third loss: -$201 | inactive | -$501 |
| 09:10:13 | **Kill switch triggers** | **ACTIVE** | — |
| 09:10:14 | Order ord_kxeth_003 already in-flight | ACTIVE | — |
| 09:10:15 | Kalshi accepts in-flight order | ACTIVE | — |
| 09:10:16 | Partial fill: 25/50 contracts | ACTIVE | -$85 |
| 09:10:17 | Kill switch blocks remaining | ACTIVE | — |
| 09:15:00 | **Zombie state detected:** position exists, can't close | ACTIVE | — |

## Root Cause

**Race Condition:** The kill switch and order submission are async. An order "in flight" (submitted but not yet responded) was accepted by Kalshi AFTER the kill switch activated.

```python
# Race condition sequence
09:10:12.500  RiskEngine.check() -> breach detected
09:10:13.000  RiskEngine._halted = True              # Kill switch ON
09:10:14.000  OrderRouter._submit() called           # Async send started
09:10:15.200  Kalshi API accepts order               # External confirmation
09:10:16.000  Partial fill notification              # Position created
09:10:17.000  RiskEngine.calculate_order_size()      # Returns 0 (blocked)
```

The position exists but the system refuses to trade it due to kill switch.

## Resolution Steps

1. ✅ **Immediate (09:16 UTC):** Manual position closure via Kalshi UI
2. ✅ **Fix (09:30 UTC):** Added `in_flight` tracking to kill switch logic
3. ✅ **Fix (10:00 UTC):** Kill switch now:
   - Blocks NEW orders immediately
   - Allows cancellation of in-flight orders for 5s
   - Tracks in-flight orders to completion
   - Flags "orphaned" positions for manual review

## DataSource Badges in Use

- **Position card:** Shows `KILL_ACTIVE` badge (red)
- **Order lineage:** Shows `kill_switch_blocked` decision point
- **Reconciliation:** Shows `pending_cancel` for in-flight orders

## Kill Switch Invariant (Property Test)

Added to `test_hypothesis_invariants.py`:

```python
@given(
    st.lists(st.just("submit_order"), min_size=1, max_size=10),
    st.booleans(),  # kill_switch_active
)
def test_kill_switch_blocks_new_but_tracks_in_flight(orders, kill_active):
    """Once kill switch trips, NEW orders blocked, IN-FLIGHT tracked."""
    if kill_active:
        # Any orders submitted AFTER kill should be blocked
        post_kill_orders = [o for o in orders if o.submitted_after_kill]
        assert all(o.status == "blocked" for o in post_kill_orders)
        
        # In-flight orders should be tracked, not just dropped
        in_flight = [o for o in orders if o.in_flight_at_kill]
        assert all(o.tracked for o in in_flight)
```

## Prevention

1. **Added:** `in_flight_orders` tracking in `RiskEngine`
2. **Added:** Property test for kill-switch race conditions
3. **Added:** "Orphaned position" alert to PagerDuty

## Replay Command

```bash
python scripts/incident_replay.py ord_kxeth_003 \
    --start-time 2026-03-22T09:10:00Z \
    --end-time 2026-03-22T09:20:00Z \
    --format markdown
```

## Post-Mortem Action Items

| Action | Owner | Status |
|--------|-------|--------|
| Add in-flight order tracking | @risk-team | ✅ Done |
| Kill switch visual banner in UI | @frontend | ✅ Done |
| Document "orphan position" handling | @sre | 🔄 In Progress |
| Add 5s grace window for cancellations | @execution | ✅ Done |
