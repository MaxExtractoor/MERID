# Example Incident 2: Reconciliation Break from Unmatched Fill

**Status:** RESOLVED  
**Severity:** P1 (High)  
**Duration:** 47 minutes  
**Reported By:** Automated reconciliation alert  
**Resolved By:** On-call engineer + manual ledger fix

---

## Timeline

```
2026-03-22T09:15:33 | order:placed      | Order ord_888 placed: KXETH-15M BUY 25 contracts
2026-03-22T09:15:34 | venue:kalshi      | Kalshi confirms: order_id kalshi-xyz789
2026-03-22T09:15:35 | fills:kalshi      | Kalshi reports partial fill: 10 contracts @ 48c
2026-03-22T09:15:36 | fills:ledger      | Fill recorded: 10 contracts @ 48c (fill_id: f_001)
2026-03-22T09:16:02 | fills:kalshi      | Kalshi reports remaining fill: 15 contracts @ 49c
2026-03-22T09:16:03 | fills:ledger      | ⚠️ Ledger write fails (network timeout)
2026-03-22T09:16:04 | position:update   | Position updated: +10 only (missing +15)
2026-03-22T09:20:00 | reconciliation    | Scheduled reconciliation scan starts
2026-03-22T09:20:05 | reconciliation    | Found unmatched fill at Kalshi: 15 contracts
2026-03-22T09:20:06 | alert:fired       | "RECONCILIATION BROKEN: unmatched fill $7.35"
2026-03-22T09:20:10 | investigation     | incident_replay.py ord_888 shows fill f_002 missing
2026-03-22T09:25:00 | manual:fix        | Fill f_002 manually added to ledger
2026-03-22T09:25:01 | position:update   | Position corrected: KXETH-15M YES +25
2026-03-22T09:25:05 | reconciliation    | Scan shows status: "ok", break_count: 0
2026-03-22T09:25:06 | alert:cleared     | Reconciliation restored
2026-03-22T10:02:00 | retrospective     | Fix deployed: retry logic + circuit breaker
```

---

## Investigation Walkthrough

### Step 1: Alert Receipt

**Alert:** "RECONCILIATION BROKEN: unmatched fill detected, value $7.35"

**Metrics:**
- `break_count`: 1
- `status`: "broken"
- `high_severity_count`: 1

### Step 2: Pull Reconciliation Breaks

```bash
$ curl http://localhost:8000/api/v1/kalshi/reconciliation/breaks | jq
```

**Response:**
```json
{
  "timestamp": "2026-03-22T09:20:06Z",
  "status": "broken",
  "threshold_usd": 5.00,
  "summary": {
    "unmatched_fills": 1,
    "unmatched_positions": 0,
    "balance_drift": 0.00,
    "pnl_divergence": 0.00
  },
  "breaks": [
    {
      "type": "unmatched_fill",
      "severity": "high",
      "message": "Fill at venue not found in ledger: kalshi-xyz789 fill 15@49c = $7.35",
      "venue_order_id": "kalshi-xyz789",
      "fill_id": "kalshi-fill-abc",
      "size": 15,
      "price_cents": 49,
      "value_usd": 7.35,
      "kalshi_timestamp": "2026-03-22T09:16:02Z"
    }
  ]
}
```

**Finding:** A fill occurred at Kalshi but is missing from our fills ledger.

### Step 3: Order Investigation

```bash
$ python scripts/incident_replay.py ord_888 --format timeline
```

**Output:**
```
2026-03-22T09:15:33 | lineage:signal    | {"action": "buy", "ticker": "KXETH-15M"}
2026-03-22T09:15:34 | lineage:router    | {"order_id": "kalshi-xyz789", "mode": "live"}
2026-03-22T09:15:35 | fill:f_001        | {"size": 10, "price_cents": 48, "status": "recorded"}
2026-03-22T09:16:02 | fill:??           | {"size": 15, "price_cents": 49, "status": "MISSING"}
```

**Finding:** Two fills occurred (10+15=25 total), but only f_001 is in our ledger. The second fill was lost.

### Step 4: Check Logs

```bash
$ grep "kalshi-xyz789" /var/log/merid/fills_ledger.log
```

**Log Output:**
```
[2026-03-22 09:15:35] INFO  fills_ledger: Recorded fill f_001 for order kalshi-xyz789 (10@48c)
[2026-03-22 09:16:03] ERROR fills_ledger: Failed to record fill: ConnectionTimeout
[2026-03-22 09:16:03] ERROR fills_ledger: Kalshi fill_id: kalshi-fill-abc, size: 15, price: 49c
[2026-03-22 09:16:03] WARNING fills_ledger: Fill lost! Manual intervention required.
```

**Finding:** Network timeout caused the second fill to be lost. Alert fired correctly.

### Step 5: Manual Fix

**Immediate fix** (to restore trading):
```bash
# Manually add missing fill to ledger
curl -X POST http://localhost:8000/api/v1/admin/fills/manual-add \
  -H "Content-Type: application/json" \
  -d '{
    "fill_id": "f_002",
    "order_id": "ord_888",
    "kalshi_fill_id": "kalshi-fill-abc",
    "ticker": "KXETH-15M",
    "side": "yes",
    "size": 15,
    "price_cents": 49,
    "timestamp": "2026-03-22T09:16:02Z",
    "reason": "Reconciliation fix: fill lost due to network timeout"
  }'
```

**Verify position updated:**
```bash
$ curl http://localhost:8000/api/v1/kalshi/positions | jq '.positions[] | select(.ticker == "KXETH-15M")'
```

**Response:**
```json
{
  "ticker": "KXETH-15M",
  "outcome": "yes",
  "size": 25,  // ✓ Corrected from 10
  "avg_price": 0.486,  // (10*48 + 15*49) / 25 = 48.6c
  "source": "fills_ledger"
}
```

### Step 6: Reconciliation Verification

```bash
$ curl http://localhost:8000/api/v1/kalshi/reconciliation/breaks | jq '.status'
```

**Response:** `"ok"`

---

## Root Cause Analysis

| Factor | Detail |
|--------|--------|
| **Trigger** | Network timeout during fills ledger write |
| **Missing Safeguard** | No retry mechanism for fill recording |
| **Missing Safeguard** | No circuit breaker to pause trading on ledger failure |
| **Why Alert Fired** | Scheduled reconciliation (every 5 min) detected mismatch |
| **Impact** | Position undervalued by $7.35, potential for double-spend |

---

## Corrective Actions

### Immediate (during incident)
1. ✓ Manual fill added to restore ledger consistency
2. ✓ Position recalculated with correct average price
3. ✓ Reconciliation scan confirms status: "ok"

### Short-term (same day)
1. **Retry Logic:** Added 3x retry with exponential backoff for fill recording
2. **Circuit Breaker:** Ledger write failures now trip circuit breaker (max 3 failures)
3. **Monitoring:** Alert on ledger write latency > 500ms

### Long-term (next sprint)
1. **Idempotency:** Fill IDs are now idempotent — safe to re-record
2. **Kalshi Reconciliation:** Daily full reconciliation with Kalshi fills API
3. **Operator Dashboard:** Reconciliation status badge added to all views

---

## Code Changes

```python
# merid/event_venues/kalshi/fills_ledger.py

async def record_fill(self, fill: Fill) -> None:
    """Record a fill with retry logic and circuit breaker."""
    
    # Check for duplicate (idempotency)
    if await self._fill_exists(fill.fill_id):
        logger.info(f"Fill {fill.fill_id} already recorded (idempotent)")
        return
    
    # Circuit breaker check
    if self.circuit_breaker.is_open():
        raise LedgerUnavailable("Circuit breaker open — ledger temporarily unavailable")
    
    # Retry logic
    for attempt in range(3):
        try:
            await self._write_fill(fill)
            return
        except ConnectionTimeout:
            if attempt < 2:
                await asyncio.sleep(2 ** attempt)  # 1s, 2s
            else:
                self.circuit_breaker.record_failure()
                raise
```

---

## Key Takeaways

1. **Reconciliation is the safety net** — Without it, the $7.35 error would persist
2. **Network timeouts happen** — Always have retry + circuit breaker
3. **Idempotency prevents double-fixes** — Safe to retry, safe to re-run
4. **47 minutes is acceptable** — Manual fix + verification, but aim for < 30 min

---

## Debug Commands Used

```bash
# 1. Check reconciliation status
curl http://localhost:8000/api/v1/kalshi/reconciliation/breaks | jq

# 2. Investigate specific order
python scripts/incident_replay.py ord_888 --format markdown

# 3. Check fills ledger logs
grep "kalshi-xyz789" /var/log/merid/fills_ledger.log

# 4. Verify position after fix
curl http://localhost:8000/api/v1/kalshi/positions | jq '.positions[] | select(.ticker == "KXETH-15M")'

# 5. Manual fill add (emergency)
curl -X POST http://localhost:8000/api/v1/admin/fills/manual-add -H "Content-Type: application/json" -d '{...}'
```
