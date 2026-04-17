# Example Incident 3: Kill Switch Race Condition

**Status:** RESOLVED  
**Severity:** P0 (Critical)  
**Duration:** 12 minutes  
**Reported By:** Automated kill switch alert + operator report  
**Resolved By:** Emergency kill switch activation + investigation

---

## Timeline

```
2026-03-23T16:45:12 | signal:btc_15m    | BUY signal (confidence: 0.87, size: 50 contracts)
2026-03-23T16:45:13 | risk:check        | Drawdown: 4.8% (under 5% threshold) — APPROVED
2026-03-23T16:45:14 | drawdown:spike    | Price drops 2% in 3 seconds — drawdown now 5.2%
2026-03-23T16:45:15 | risk:kill_switch  | Trip triggered: drawdown > 5%
2026-03-23T16:45:15 | kill_switch:state | ACTIVE — All live orders blocked
2026-03-23T16:45:16 | router:order      | ⚠️ Race condition: Order already in flight (sent at 16:45:15.8)
2026-03-23T16:45:16 | venue:kalshi      | ⚠️ Kalshi accepts order kalshi-race001 (sent before kill ack)
2026-03-23T16:45:17 | fills:kalshi      | ⚠️ Fill recorded: 50 contracts @ 45c (price still dropping)
2026-03-23T16:45:18 | alert:fired       | "Kill switch active but live order executed: kalshi-race001"
2026-03-23T16:45:19 | investigation     | incident_replay.py shows kill_switch @ 16:45:15, order @ 16:45:16
2026-03-23T16:45:25 | action:taken      | Emergency kill all positions — flattened in paper mode
2026-03-23T16:45:30 | mode:switched     | Profile switched to HALTED for manual review
2026-03-23T16:48:00 | retrospective     | Confirmed: 300ms race window between risk check and kill ack
2026-03-23T16:50:00 | fix:deployed     | Order router now subscribes to kill_switch feed (sub-ms latency)
2026-03-23T16:57:00 | mode:restored     | Back to LIVE after review
```

---

## Investigation Walkthrough

### Step 1: Alert Receipt

**Alert:** "CRITICAL: Kill switch active but live order executed — kalshi-race001"

**State at alert time:**
- Kill switch: ACTIVE (tripped at 16:45:15)
- Order executed: 16:45:16 (1 second AFTER kill switch)
- Order mode: "live"

This violates the core invariant: **Once kill switch trips, no further live orders are ever produced.**

### Step 2: State Transition Analysis

```bash
$ python scripts/incident_replay.py ord_race001 --format timeline --window-minutes 5
```

**Output:**
```
2026-03-23T16:45:12.100 | lineage:signal    | {"action": "buy", "size": 50}
2026-03-23T16:45:12.500 | lineage:agent     | {"agent_id": "btc_15m", "action": "buy"}
2026-03-23T16:45:13.200 | lineage:consensus | {"approved": true, "confidence": 0.85}
2026-03-23T16:45:13.800 | lineage:risk      | {"allowed": true, "drawdown": 4.8}
2026-03-23T16:45:14.200 | market:drop       | {"price_drop": 0.02, "time_ms": 3000}
2026-03-23T16:45:15.000 | risk:kill_switch  | {"trigger": "drawdown", "threshold": 5.0, "actual": 5.2}
2026-03-23T16:45:15.100 | kill_switch:state | {"active": true}
2026-03-23T16:45:15.800 | lineage:router    | {"order_sent": true, "kill_switch_checked": false}
2026-03-23T16:45:16.200 | venue:kalshi      | {"accepted": true, "order_id": "kalshi-race001"}
```

**Finding:** The order was sent at 16:45:15.8, but the kill switch state change was only seen by the router AFTER the order was already in flight.

### Step 3: Race Condition Analysis

```
Timeline (millisecond precision):

16:45:15.000 | Risk controller detects drawdown > 5%
16:45:15.050 | Risk controller writes kill_switch_active = true
16:45:15.100 | State transition logger records kill switch trip
16:45:15.200 | Kill switch notification sent (async)
16:45:15.300 | Order router checks kill switch (reads false — stale read)
16:45:15.800 | Order router sends order to Kalshi
16:45:15.900 | Order router receives kill switch notification
16:45:16.200 | Kalshi accepts order

Race window: ~800ms between kill switch trip and router awareness
```

**Root cause:** The order router polled for kill switch status at 16:45:15.3, but the kill switch was written at 16:45:15.05. The router used a cached/stale value.

### Step 4: Code Inspection

**Before (buggy):**
```python
# merid/event_venues/kalshi/order_router.py (old)
async def route_order_async(intent: OrderIntent) -> RouteResult:
    # Check kill switch (poll-based, cached)
    if risk_controller.get_kill_switch_state():  # Cached, may be stale
        return RouteResult.blocked("kill_switch_active")
    
    # Send order
    return await self._send_to_venue(intent)
```

**Problem:** `get_kill_switch_state()` returned a cached value from 500ms ago.

### Step 5: Immediate Actions

1. **Emergency kill all positions** — Prevent further exposure
   ```bash
   curl -X POST http://localhost:8000/api/v1/kalshi/kill-all-positions \
     -H "Content-Type: application/json" \
     -d '{"mode": "paper", "reason": "Kill switch race condition investigation"}'
   ```

2. **Switch to HALTED mode**
   ```bash
   curl -X POST http://localhost:8000/api/v1/system/mode \
     -H "Content-Type: application/json" \
     -d '{"mode": "HALTED", "reason": "Manual review after kill switch race"}'
   ```

3. **Verify no more orders can execute**
   ```bash
   curl http://localhost:8000/api/v1/kalshi/risk | jq '.kill_switch_active'
   # true
   
   curl http://localhost:8000/api/v1/system/mode
   # HALTED
   ```

### Step 6: Fix Implementation

**Solution:** Event-driven kill switch with sub-millisecond latency.

```python
# merid/event_venues/kalshi/order_router.py (fixed)
class OrderRouter:
    def __init__(self):
        self._kill_switch_event = asyncio.Event()
        self._kill_switch_active = False
        
    async def _subscribe_kill_switch(self):
        """Subscribe to real-time kill switch changes."""
        async for state in risk_controller.kill_switch_feed():
            self._kill_switch_active = state
            if state:
                self._kill_switch_event.set()
    
    async def route_order_async(self, intent: OrderIntent) -> RouteResult:
        # Immediate check (event-based, no cache)
        if self._kill_switch_active or self._kill_switch_event.is_set():
            return RouteResult.blocked("kill_switch_active")
        
        # Atomic check-and-send with timeout
        try:
            async with asyncio.timeout(0.1):  # 100ms max
                return await self._send_to_venue(intent)
        except asyncio.TimeoutError:
            # Re-check kill switch before retry
            if self._kill_switch_active:
                return RouteResult.blocked("kill_switch_active_timeout")
            raise
```

**Additional safeguards:**
1. **Pre-flight check:** Re-verify kill switch in the same event loop tick before HTTP send
2. **Post-flight verify:** If kill switch trips during send, attempt immediate cancel
3. **Circuit breaker:** On kill switch trip, circuit breaker opens for 5 seconds (cooldown)

### Step 7: Verification

```bash
# Deploy fix
make deploy-hotfix-kill-switch

# Run red team test with kill switch stress
python scripts/ci_red_team.py --scenario kill_switch_race --duration 60

# Verify no orders slip through
# (test generates 100 orders while randomly triggering kill switch)
```

**Test results:**
- 100 orders generated
- 47 orders blocked by kill switch (expected)
- 0 orders slipped through (previously: 1-2 would race)

---

## Root Cause Analysis

| Factor | Detail |
|--------|--------|
| **Trigger** | 2% price drop in 3 seconds caused drawdown spike |
| **Race Window** | ~800ms between kill switch write and router awareness |
| **Mechanism** | Polling-based kill switch check with 500ms cache |
| **Why Invariant Failed** | Router used stale cached state |
| **Impact** | 1 live order executed after kill switch trip (50 contracts, $22.50 exposure) |

---

## Corrective Actions

### Immediate (during incident)
1. ✓ Emergency position flattening (paper mode)
2. ✓ HALTED mode activated
3. ✓ Manual review confirmed no further exposure

### Hotfix (12 minutes)
1. ✓ Event-driven kill switch subscription (sub-ms latency)
2. ✓ Atomic check-and-send with pre/post verification
3. ✓ Circuit breaker cooldown period

### Long-term (next sprint)
1. **Deterministic kill switch:** Use Redis/pub-sub for state sync
2. **Order ID reservation:** Reserve order ID before kill switch check, cancel if kill trips
3. **Kill switch ack protocol:** Require explicit acknowledgment from all components
4. **CI test:** `TestKillSwitchRaceCondition` — 10k iterations, zero tolerance for races

---

## Invariant Violation Summary

| Invariant | Expected | Actual | Status |
|-----------|----------|--------|--------|
| `kill_switch_blocks_live` | Once active, no live orders | 1 order executed | ❌ VIOLATED |
| `state_transition_logged` | Kill switch trip logged | Logged at 16:45:15.100 | ✓ OK |
| `kill_switch_consistency` | /risk and /operator agree | Both showed active | ✓ OK |

---

## Key Takeaways

1. **Polling is dangerous for kill switches** — Use event-driven with < 1ms latency
2. **Race windows exist even in "safe" code** — Always re-verify at point of action
3. **Invariant violations are P0** — Stop everything, investigate, fix, verify
4. **12 minutes is fast response** — But aim for prevention, not response

---

## Debug Commands Used

```bash
# 1. Incident replay with extended window
python scripts/incident_replay.py ord_race001 --format timeline --window-minutes 5

# 2. Check kill switch state transitions
curl http://localhost:8000/api/v1/kalshi/health/reconciliation | jq '.state_transitions[] | select(.type == "kill_switch")'

# 3. Emergency kill switch (manual trigger)
curl -X POST http://localhost:8000/api/v1/kalshi/kill-switch/trigger \
  -H "Content-Type: application/json" \
  -d '{"reason": "Manual emergency stop", "triggered_by": "oncall-engineer"}'

# 4. Mode switch to HALTED
curl -X POST http://localhost:8000/api/v1/system/mode \
  -H "Content-Type: application/json" \
  -d '{"mode": "HALTED", "reason": "Investigation"}'

# 5. Verify no live orders possible
curl http://localhost:8000/api/v1/kalshi/risk | jq '{kill_switch: .kill_switch_active, mode: .trading_mode}'
```

---

## Post-Mortem Actions

1. **Updated runbook:** Added "Race Condition Detection" section
2. **CI test added:** `test_kill_switch_no_race_condition` (10000 iterations)
3. **Monitoring:** Alert if order placed < 5 seconds after kill switch trip
4. **Training:** Incident review session with all engineers (scheduled)
