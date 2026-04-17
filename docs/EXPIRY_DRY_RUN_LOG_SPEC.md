# EXPIRY_DRY_RUN_LOG_SPEC.md

**Purpose:** Structured log fields and grep patterns for expiry chaos dry runs.

**Part of:** Kalshi Expiry Chaos Audit - Follow-on Phase

---

## 1. Structured Log Field Specification

### 1.1 Required Log Fields by Component

#### KalshiTradingAgent (`merid/prediction/trading_agent.py`)

| Field | Type | Example | Purpose |
|-------|------|---------|---------|
| `event` | string | `"expiry_proximity_check"` | Identifies log type |
| `market_id` | string | `"KXBTC-20250115-15M"` | Target market |
| `seconds_to_expiry` | float | `87.5` | Calculated time to expiry |
| `guard_decision` | string | `"block"` \| `"warn"` \| `"pass"` | Action taken |
| `reason` | string | `"expiry_proximity_guard:seconds_to_expiry=87"` | Human-readable rationale |
| `agent_id` | string | `"kalshi_btc_15m_trend_01"` | Source agent |
| `timestamp_utc` | ISO8601 | `"2025-01-15T14:58:32.445Z"` | Event time |

**Example Log Lines:**
```json
{"event": "expiry_proximity_check", "market_id": "KXBTC-20250115-15M", "seconds_to_expiry": 87.5, "guard_decision": "block", "reason": "expiry_proximity_guard:seconds_to_expiry=87", "agent_id": "kalshi_btc_15m_trend_01", "timestamp_utc": "2025-01-15T14:58:32.445Z", "level": "DEBUG"}

{"event": "expiry_approaching_warning", "market_id": "KXBTC-20250115-15M", "seconds_to_expiry": 115.2, "guard_decision": "warn", "reason": "entering_caution_zone", "agent_id": "kalshi_btc_15m_trend_01", "timestamp_utc": "2025-01-15T14:57:44.123Z", "level": "WARNING"}
```

---

#### SettlementExecutionGuard (`merid/event_venues/kalshi/settlement_execution_guard.py`)

| Field | Type | Example | Purpose |
|-------|------|---------|---------|
| `event` | string | `"settlement_guard_eval"` | Identifies evaluation |
| `ticker` | string | `"KXBTC-20250115-15M"` | Target ticker |
| `action` | string | `"buy"` \| `"sell"` | Order side |
| `seconds_to_expiry` | float | `45.0` | Time remaining |
| `decision` | string | `"allow"` \| `"block"` | Guard outcome |
| `block_reason` | string | `"rti_settlement_window:no_new_buys"` | Rejection code |
| `policy` | string | `"reduce_ok"` \| `"block_all"` | Active policy |
| `buffer_filled_count` | int | `58` | RTI slots filled |
| `buffer_is_grade` | bool | `false` | Settlement grade status |
| `extended_guard_active` | bool | `true` | Using 120s extended window |

**Example Log Lines:**
```json
{"event": "settlement_guard_eval", "ticker": "KXBTC-20250115-15M", "action": "buy", "seconds_to_expiry": 45.0, "decision": "block", "block_reason": "rti_settlement_window:no_new_buys", "policy": "reduce_ok", "buffer_filled_count": 58, "buffer_is_grade": false, "timestamp_utc": "2025-01-15T14:59:15.000Z"}

{"event": "extended_guard_active", "ticker": "KXBTC-20250115-15M", "seconds_to_expiry": 95.0, "buffer_filled_count": 52, "buffer_is_grade": false, "action": "buy", "decision": "block", "block_reason": "rti_settlement_window:extended_guard_incomplete_data:t-95s", "timestamp_utc": "2025-01-15T14:58:25.000Z", "level": "WARNING"}

{"event": "settlement_guard_eval", "ticker": "KXBTC-20250115-15M", "action": "sell", "seconds_to_expiry": 45.0, "decision": "allow", "policy": "reduce_ok", "buffer_filled_count": 58, "buffer_is_grade": false, "timestamp_utc": "2025-01-15T14:59:15.000Z"}
```

---

#### OrderRouter (`merid/event_venues/kalshi/order_router.py`)

| Field | Type | Example | Purpose |
|-------|------|---------|---------|
| `event` | string | `"order_routing_decision"` | Routing outcome |
| `intent_id` | string | `"intent_a1b2c3d4"` | Order identifier |
| `ticker` | string | `"KXBTC-20250115-15M"` | Target market |
| `action` | string | `"buy"` \| `"sell"` | Order side |
| `seconds_to_expiry` | float | `87.5` | Expiry proximity |
| `settlement_guard_passed` | bool | `false` | Guard clearance |
| `routed_to` | string | `"paper"` \| `"live"` \| `"rejected"` | Execution path |
| `rejection_reason` | string | `"rti_settlement_window:no_new_buys"` | If blocked |

**Example Log Lines:**
```json
{"event": "order_routing_decision", "intent_id": "intent_a1b2c3d4", "ticker": "KXBTC-20250115-15M", "action": "buy", "seconds_to_expiry": 87.5, "settlement_guard_passed": false, "routed_to": "rejected", "rejection_reason": "rti_settlement_window:no_new_buys", "timestamp_utc": "2025-01-15T14:58:32.500Z"}
```

---

#### RTI Settlement Buffer (`merid/data/settlement_rti_buffer.py`)

| Field | Type | Example | Purpose |
|-------|------|---------|---------|
| `event` | string | `"buffer_status"` | Buffer state |
| `ticker` | string | `"KXBTC-20250115-15M"` | Target ticker |
| `filled_count` | int | `58` | Slots filled |
| `required_count` | int | `60` | Target slots |
| `is_settlement_grade` | bool | `false` | Grade status |
| `oldest_sample_age_ms` | int | `4500` | Staleness check |
| `newest_sample_age_ms` | int | `500` | Freshness check |

**Example Log Lines:**
```json
{"event": "buffer_status", "ticker": "KXBTC-20250115-15M", "filled_count": 58, "required_count": 60, "is_settlement_grade": false, "oldest_sample_age_ms": 4500, "newest_sample_age_ms": 500, "timestamp_utc": "2025-01-15T14:58:30.000Z"}

{"event": "buffer_grade_achieved", "ticker": "KXBTC-20250115-15M", "filled_count": 60, "is_settlement_grade": true, "timestamp_utc": "2025-01-15T14:58:45.000Z"}
```

---

## 2. Grep Patterns for Log Analysis

### 2.1 Core Validation Patterns

```bash
# Pattern 1: Find all expiry proximity blocks (Gap G1 verification)
grep -E 'expiry_proximity_guard.*seconds_to_expiry' logs/dry_run.log | \
  jq -r '[.timestamp_utc, .market_id, .seconds_to_expiry, .guard_decision] | @tsv'

# Pattern 2: Find all settlement guard evaluations
grep -E 'settlement_guard_eval' logs/dry_run.log | \
  jq -r '[.timestamp_utc, .ticker, .action, .seconds_to_expiry, .decision, .block_reason] | @tsv'

# Pattern 3: Find extended guard activations (Gap G4 verification)
grep -E 'extended_guard_active' logs/dry_run.log | \
  jq -r '[.timestamp_utc, .ticker, .seconds_to_expiry, .buffer_filled_count] | @tsv'

# Pattern 4: Find orders blocked within 90s (Invariant check)
grep -E 'order_routing_decision.*rejected' logs/dry_run.log | \
  jq 'select(.seconds_to_expiry <= 90)' | \
  jq -r '[.timestamp_utc, .ticker, .seconds_to_expiry, .rejection_reason] | @tsv'

# Pattern 5: Find 120s warnings (Caution zone entry)
grep -E 'expiry_approaching_warning' logs/dry_run.log | \
  jq -r '[.timestamp_utc, .market_id, .seconds_to_expiry] | @tsv'
```

### 2.2 Statistical Analysis Patterns

```bash
# Count blocks by time bucket
grep -E 'settlement_guard_eval.*decision.*block' logs/dry_run.log | \
  jq -r '.seconds_to_expiry' | \
  awk '{if($1<=60) print "0-60s"; else if($1<=90) print "60-90s"; else if($1<=120) print "90-120s"; else print ">120s"}' | \
  sort | uniq -c

# Verify no buys allowed within 90s (should return empty)
grep -E 'settlement_guard_eval.*action.*buy.*decision.*allow' logs/dry_run.log | \
  jq 'select(.seconds_to_expiry <= 90)' | \
  wc -l
# Expected: 0

# Verify sells allowed within 60s (should show >0)
grep -E 'settlement_guard_eval.*action.*sell.*decision.*allow' logs/dry_run.log | \
  jq 'select(.seconds_to_expiry <= 60)' | \
  wc -l
# Expected: >0 (reduce-only mode working)

# Check extended guard triggers
grep -E 'extended_guard_active' logs/dry_run.log | wc -l
# Should correlate with buffer <60 slots near expiry
```

### 2.3 Timeline Reconstruction Pattern

```bash
# Build chronological trace for a specific expiry
ticker="KXBTC-20250115-15M"
grep -E "$ticker" logs/dry_run.log | \
  jq -s 'sort_by(.timestamp_utc)' | \
  jq -r '.[] | [.timestamp_utc, .event, .seconds_to_expiry // "N/A", .guard_decision // .decision // "N/A", .reason // .block_reason // "N/A"] | @tsv'
```

---

## 3. Dry Run Verification Checklist

### Pre-Run Setup

- [ ] Confirm `MERID_RTI_SETTLEMENT_FINAL_SECONDS=60` in environment
- [ ] Confirm `MERID_FILTER_RTI_MIN_SECONDS=61` in environment
- [ ] Confirm `MERID_RTI_EXTENDED_GUARD_SECONDS=120` in environment
- [ ] Confirm `MERID_RTI_ALLOW_BUY_IF_SETTLEMENT_GRADE` unset or false
- [ ] Set log level to DEBUG for all components
- [ ] Enable structured JSON logging
- [ ] Identify target expiry windows (recommend: 2x daily + 2x 15m)

### During Run (T-5m to Settlement)

| Time | Action | Expected Evidence |
|------|--------|-------------------|
| T-5m | Start log capture | All components initialized |
| T-3m | Verify buffer filling | `buffer_status` showing increasing `filled_count` |
| T-2m | Watch for 120s warnings | `expiry_approaching_warning` events |
| T-90s | Verify 90s hard blocks begin | `expiry_proximity_guard:seconds_to_expiry=8[0-9]` |
| T-60s | Verify settlement guard active | `settlement_guard_eval` showing `decision: block` for buys |
| T-60s | Verify sells still allowed | `settlement_guard_eval` showing `decision: allow` for sells |
| T-30s | Verify no new buys | Zero `order_routing_decision` with `routed_to: live/paper` for buys |
| T-0 | Settlement | `buffer_grade_achieved` or final status logged |

### Post-Run Validation

```bash
#!/bin/bash
# run_validation.sh - Post-dry-run verification

LOG_FILE="${1:-logs/dry_run.log}"
TICKER="${2:-KXBTC-20250115-15M}"

echo "=== EXPIRY DRY RUN VALIDATION ==="
echo "Log file: $LOG_FILE"
echo "Ticker: $TICKER"
echo ""

# Check 1: No buys within 90s
echo "Check 1: No buys allowed within 90s..."
buys_within_90s=$(grep -E 'settlement_guard_eval.*action.*buy.*decision.*allow' "$LOG_FILE" | \
  jq 'select(.seconds_to_expiry <= 90)' | wc -l)
if [ "$buys_within_90s" -eq 0 ]; then
    echo "✅ PASS: No buys within 90s (count: $buys_within_90s)"
else
    echo "❌ FAIL: Found $buys_within_90s buys within 90s"
fi
echo ""

# Check 2: Extended guard activates when buffer <60
echo "Check 2: Extended guard activates with incomplete buffer..."
extended_count=$(grep -E 'extended_guard_active' "$LOG_FILE" | wc -l)
if [ "$extended_count" -gt 0 ]; then
    echo "✅ PASS: Extended guard activated $extended_count times"
else
    echo "⚠️  WARNING: No extended guard activations (may be OK if buffer always full)"
fi
echo ""

# Check 3: Sells allowed within 60s (reduce-only mode)
echo "Check 3: Sells allowed within 60s (reduce-only mode)..."
sells_within_60s=$(grep -E 'settlement_guard_eval.*action.*sell.*decision.*allow' "$LOG_FILE" | \
  jq 'select(.seconds_to_expiry <= 60)' | wc -l)
if [ "$sells_within_60s" -gt 0 ]; then
    echo "✅ PASS: $sells_within_60s sells allowed within 60s"
else
    echo "⚠️  WARNING: No sells within 60s (may be OK if no positions to close)"
fi
echo ""

# Check 4: 120s warnings present
echo "Check 4: 120s warning zone logged..."
warnings_120s=$(grep -E 'expiry_approaching_warning' "$LOG_FILE" | wc -l)
if [ "$warnings_120s" -gt 0 ]; then
    echo "✅ PASS: $warnings_120s warnings at 120s boundary"
else
    echo "❌ FAIL: No 120s warnings found"
fi
echo ""

# Check 5: Agent 90s blocks present
echo "Check 5: Agent 90s hard blocks present..."
agent_blocks=$(grep -E 'expiry_proximity_guard.*block' "$LOG_FILE" | wc -l)
if [ "$agent_blocks" -gt 0 ]; then
    echo "✅ PASS: $agent_blocks agent blocks recorded"
else
    echo "❌ FAIL: No agent blocks found"
fi
echo ""

# Check 6: Buffer status progression
echo "Check 6: Buffer filling progression..."
grep -E 'buffer_status.*"ticker":"'$TICKER'"' "$LOG_FILE" | \
  jq -r '[.timestamp_utc, .filled_count, .is_settlement_grade] | @tsv' | \
  sort
echo ""

echo "=== VALIDATION COMPLETE ==="
```

---

## 4. Example Complete Log Slice

**Scenario:** KXBTC-20250115-15M expiry, buffer at 58/60 at T-95s, agent attempts buy at T-87s

```json
{"timestamp_utc": "2025-01-15T14:58:25.000Z", "event": "buffer_status", "ticker": "KXBTC-20250115-15M", "filled_count": 58, "required_count": 60, "is_settlement_grade": false, "level": "DEBUG"}
{"timestamp_utc": "2025-01-15T14:58:25.100Z", "event": "extended_guard_active", "ticker": "KXBTC-20250115-15M", "seconds_to_expiry": 94.9, "buffer_filled_count": 58, "buffer_is_grade": false, "action": "buy", "decision": "block", "block_reason": "rti_settlement_window:extended_guard_incomplete_data:t-95s", "level": "WARNING"}
{"timestamp_utc": "2025-01-15T14:58:32.445Z", "event": "expiry_proximity_check", "market_id": "KXBTC-20250115-15M", "seconds_to_expiry": 87.5, "guard_decision": "block", "reason": "expiry_proximity_guard:seconds_to_expiry=87", "agent_id": "kalshi_btc_15m_trend_01", "level": "DEBUG"}
{"timestamp_utc": "2025-01-15T14:58:32.500Z", "event": "order_routing_decision", "intent_id": "intent_a1b2c3d4", "ticker": "KXBTC-20250115-15M", "action": "buy", "seconds_to_expiry": 87.5, "settlement_guard_passed": false, "routed_to": "rejected", "rejection_reason": "rti_settlement_window:extended_guard_incomplete_data:t-95s", "level": "INFO"}
{"timestamp_utc": "2025-01-15T14:59:15.000Z", "event": "settlement_guard_eval", "ticker": "KXBTC-20250115-15M", "action": "sell", "seconds_to_expiry": 45.0, "decision": "allow", "policy": "reduce_ok", "buffer_filled_count": 60, "buffer_is_grade": true, "level": "DEBUG"}
```

---

## 5. Log Verification Grep Cheat Sheet

| What to Verify | Grep Pattern | Expected Result |
|----------------|--------------|-----------------|
| 90s blocks working | `grep 'expiry_proximity_guard.*seconds_to_expiry=[0-8][0-9]'` | Lines present |
| No 90s+ buys | `grep 'settlement_guard_eval.*buy.*allow' \| jq 'select(.seconds_to_expiry<=90)'` | Empty |
| Extended guard triggers | `grep 'extended_guard_active'` | Lines when buffer<60 |
| 120s warnings | `grep 'expiry_approaching_warning'` | Lines present |
| Sells allowed | `grep 'settlement_guard_eval.*sell.*allow'` | Lines present |
| Buffer progression | `grep 'buffer_status.*filled_count'` | Shows 0→60 progression |

---

## Related Documents

- `EXPIRY_CHAOS_TEST_PLAN.md` — Test scenarios
- `EXPIRY_LEDGER_INVARIANTS.md` — Ledger consistency rules
- `EXPIRY_CHAOS_GO_NO_GO.md` — Readiness checklist

---

*Document Version: 1.0*
*Last Updated: 2025-01-26*
*Part of: Kalshi Expiry Chaos Audit*
