# Example Incident 1: Incomplete Lineage (Ghost Order)

**Status:** RESOLVED  
**Severity:** P1 (High)  
**Duration:** 23 minutes  
**Reported By:** Operator dashboard alert  
**Resolved By:** On-call engineer (auto-resolved via flag correction)

---

## Timeline

```
2026-03-20T14:23:17 | lineage:signal    | BTC_15M agent emits BUY signal (confidence: 0.84)
2026-03-20T14:23:18 | lineage:consensus | TaCo approves signal (confidence: 0.81)
2026-03-20T14:23:19 | lineage:risk      | Risk controller allows order (drawdown: 2.3%)
2026-03-20T14:23:20 | lineage:router    | Order routed: ord_btc15m_001
2026-03-20T14:23:21 | venue:kalshi      | Kalshi accepts order (order_id: kalshi-abc123)
2026-03-20T14:23:22 | fills:ledger      | Fill recorded: 10 contracts @ 52 cents
2026-03-20T14:23:23 | position:update   | Position updated: KXBTC-15M YES +10
2026-03-20T14:24:00 | alert:fired       | Ghost order detected: ord_migrate_002
2026-03-20T14:24:01 | lineage:check     | found: true, chain_complete: false, coverage: "1/4"
2026-03-20T14:24:02 | investigation     | Order has no signal/consensus/risk trace
2026-03-20T14:24:03 | whitelist:check   | Order from scripts/migrate_positions_legacy.py
2026-03-20T14:24:04 | resolution        | manual_or_external flag set to true
2026-03-20T14:24:05 | ui:update         | Badge changes from yellow (PARTIAL) to orange (EXTERNAL)
2026-03-20T14:24:06 | alert:cleared     | Investigation complete
```

---

## Investigation Walkthrough

### Step 1: Initial Alert

**Alert:** "Ghost order detected: ord_migrate_002 has incomplete lineage"

**Operator Action:** Checked Kalshi Dashboard — saw order with yellow "PARTIAL" badge

### Step 2: Pull Lineage

```bash
$ curl http://localhost:8000/api/v1/kalshi/orders/ord_migrate_002/lineage | jq
```

**Response:**
```json
{
  "order_id": "ord_migrate_002",
  "found": true,
  "chain_complete": false,
  "chain_coverage": "1/4",
  "manual_or_external": false,
  "synthetic": false,
  "venue_source": "executor",
  "chain": {
    "router": {
      "route_call_id": "rt_789",
      "mode": "live",
      "timestamp": "2026-03-20T14:24:00Z"
    }
    // signal, agent, consensus, risk MISSING
  },
  "warnings": [
    "Missing signal trace — order has no initiating signal",
    "Missing consensus approval — order bypassed TaCo",
    "Missing risk decision — order has no risk controller record"
  ]
}
```

**Finding:** Order has router trace but no upstream lineage. This is a "phantom" order that appeared at the router without normal pipeline flow.

### Step 3: Check Source

```bash
$ grep -r "ord_migrate_002" merid/
# No results in normal code

$ grep -r "ord_migrate_002" scripts/
scripts/migrate_positions_legacy.py:    order_id = "ord_migrate_002"
```

**Finding:** Order was created by migration script `scripts/migrate_positions_legacy.py`.

### Step 4: Check Whitelist

```bash
$ cat .ci/venue_touchpoint_whitelist.txt
```

**Finding:** `scripts/migrate_positions_legacy.py` is whitelisted as a manual migration tool.

### Step 5: Resolution

The migration script correctly used the router, but failed to set `manual_or_external: true`.

**Fix:** Patch migration script to set flag:
```python
# In scripts/migrate_positions_legacy.py
intent = OrderIntent(...)
intent.manual_or_external = True  # Added
intent.external_reason = "Legacy position migration"
```

**Immediate Fix:** Database update to set flag on existing order:
```bash
curl -X POST http://localhost:8000/api/v1/admin/orders/ord_migrate_002/flag \
  -H "Content-Type: application/json" \
  -d '{"manual_or_external": true, "reason": "Legacy migration"}'
```

### Step 6: Verification

```bash
$ curl http://localhost:8000/api/v1/kalshi/orders/ord_migrate_002/lineage | jq
```

**Response:**
```json
{
  "order_id": "ord_migrate_002",
  "found": true,
  "chain_complete": false,
  "manual_or_external": true,  // ✓ Now flagged
  "synthetic": false,
  "warnings": ["External/manual order — review intentional"]
}
```

**UI Update:** Badge changed from yellow "PARTIAL" to orange "EXTERNAL"

---

## Root Cause Analysis

| Factor | Detail |
|--------|--------|
| **Trigger** | Migration script created order via router without lineage flags |
| **Why CI Didn't Catch** | Script is whitelisted, but flag enforcement was missing |
| **Why Alert Fired** | `TestOrderLineageInvariants.test_no_incomplete_lineage_without_external_flag` failed |
| **Systemic Issue** | Whitelisted scripts need explicit flag documentation |

---

## Corrective Actions

1. **Immediate:** All migration scripts updated to set `manual_or_external: true`
2. **CI:** Added guardrail test `test_whitelisted_scripts_set_flags`
3. **Documentation:** Migration runbook updated with flag requirements
4. **Monitoring:** Alert now includes link to whitelist entry

---

## Key Takeaways

1. **Lineage gaps are not always bugs** — sometimes they're intentional external orders
2. **The flag is the signal** — `manual_or_external: true` tells operators "this is expected"
3. **Whitelist + flags** — Combination prevents false positives while maintaining traceability
4. **5-minute resolution** — incident_replay.py + whitelist check = fast diagnosis

---

## Debug Commands Used

```bash
# 1. Pull lineage
python scripts/incident_replay.py ord_migrate_002 --format markdown

# 2. Search for order source
grep -r "ord_migrate_002" scripts/

# 3. Check whitelist
cat .ci/venue_touchpoint_whitelist.txt | grep migrate

# 4. Verify fix
curl http://localhost:8000/api/v1/kalshi/orders/ord_migrate_002/lineage | jq

# 5. Check UI state
curl http://localhost:8000/api/v1/kalshi/orders | jq '.orders[] | select(.order_id == "ord_migrate_002") | {synthetic, manual_or_external}'
```
