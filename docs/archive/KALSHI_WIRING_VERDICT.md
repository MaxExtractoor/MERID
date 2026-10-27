# MERID Kalshi Integration — Operational Wiring Report
## Runtime Audit Operationalization & Pass/Fail Verdict

**Date:** 2026-03-30  
**Scope:** fills_ledger.py, fills_poller.py, kalshi_api.py (fills/positions/orders)  
**Source Blueprint:** `docs/KALSHI_RUNTIME_AUDIT_REPORT.md`

---

## 1. Section → Artifacts Mapping

| Section | Summary | Concrete Artifacts to Touch |
|---------|---------|----------------------------|
| 1. Test Narratives | 5 trade scenarios from simple buy to WS/HTTP race | `merid/event_venues/kalshi/fills_ledger.py:_fills`, `web/api/kalshi_api.py:/fills`, `/positions`, Kalshi REST API (test creds), WebSocket connection logs |
| 2. Fills Ledger Probes | Uniqueness, sign, fee, timestamp, recovery validation | `fills_ledger.py:_fill_ids` (set), `add_fill()` logs, `_ledger_fill_price_usd()` output, SQLite `kalshi_fills` table |
| 3. Fills Poller Probes | Pagination gaps, restart behavior, TOCTOU, WS/HTTP collision | `fills_poller.py:cursor`, `_last_poll_time`, HTTP response pagination, `asyncio.Queue` for WS fills, `threading.Lock` presence/absence |
| 4. Fills Endpoint Contracts | Default filters, sort order, ID schema mismatches | Raw Kalshi `/fills?since=` responses, `kalshi_api.py:get_fills()` return shape, `since_hours` param handling |
| 5. Positions Endpoint | Invariants between fills sum and position size | `kalshi_api.py:get_positions()`, `rest.get_positions()` raw output, `executor.get_positions()` if configured |
| 6. Orders Endpoints | State machine, env, side, price, rejection handling | 11 endpoint handlers in `kalshi_api.py`, `KalshiOrder` type validation, `SIDE` enum usage |
| 7. Cross-Layer Invariants | 6 invariants across fills→ledger→positions→portfolio | `discover-health` endpoint output, reconciliation job logs, PNL divergence alerts |
| 8. Immediate Actions | Logs, metrics, repro tests, code hooks | `logger.info()` calls, Prometheus metrics, `pytest` test cases, `threading.RLock()` additions |

---

## 2. Executable Probes — 5 Test Narratives

### Probe A: Single YES Buy → Partial Close

**Exact Orders to Issue:**
```python
# Order 1: BUY YES 10 @ 45¢ (limit, GTC)
order_1 = {
    "ticker": "BTC-250328-CALL-85000",
    "side": "yes",
    "action": "buy",
    "size": 10,
    "price": 45,  # cents
    "type": "limit",
    "tif": "gtc"
}
# Wait for fill confirmation (≤5s in normal market)

# Order 2: SELL YES 4 @ 52¢ (limit, GTC)
order_2 = {
    "ticker": "BTC-250328-CALL-85000",
    "side": "yes",
    "action": "sell",
    "size": 4,
    "price": 52,
    "type": "limit",
    "tif": "gtc"
}
```

**Expected Event Sequence:**
1. T+0s: POST `/orders` → 200, `order_id=ORD-001`, `status=live`
2. T+2s: Kalshi fill arrives → WS push or HTTP poll
3. T+2s: `/fills` shows 1 fill: `{"fill_id":"FILL-001","size":10,"price":45,"side":"yes"}`
4. T+2s: `/positions` shows `{"ticker":"BTC-250328-CALL-85000","size":10,"avg_price":45}`
5. T+5s: POST second order → 200, `order_id=ORD-002`
6. T+7s: Second fill → `/fills` shows 2 fills
7. T+7s: `/positions` shows `size=6`, avg price still 45 (FIFO)

**Invariants to Validate:**
1. `len(fills_ledger._fills) == 2` (not 1, not 3)
2. `fills_ledger._fill_ids` contains both `FILL-001` and fill from second order
3. Position size = 10 - 4 = 6
4. Realized PNL = 4 × (52 - 45) - fees = $0.28 - $0.208 = $0.072 (not $0.28, not $0)

**Evidence Criteria:**
- **Bug Present:** Position shows 10 after both fills, or shows 4 (sign flipped), or fills count ≠ 2
- **Bug Absent:** All invariants hold within 10 seconds of second fill

---

### Probe B: Fast Flip Around Close

**Exact Orders to Issue:**
```python
# Submit both within 2 seconds
flip_buy = {
    "ticker": "SPY-250401-RANGE-520-530",
    "side": "yes",
    "action": "buy",
    "size": 50,
    "price": 48,
    "type": "market"  # Market for speed
}
flip_sell = {
    "ticker": "SPY-250401-RANGE-520-530",
    "side": "yes",
    "action": "sell",
    "size": 50,
    "price": 52,
    "type": "market"
}
# Submit via asyncio.gather or rapid sequential calls
```

**Expected Event Sequence:**
1. T+0s: Both orders submitted
2. T+0.5s: Kalshi may batch or sequence fills
3. T+1s: `/fills` shows 2 fills (order not guaranteed)
4. T+1s: `/positions` shows `size=0`
5. T+1s: Realized PNL = 50 × (52 - 48) - fees = $2.00 - fees

**Invariants to Validate:**
1. Final position = 0 (not 50, not -50, not 1 due to slippage)
2. Both fills have distinct `fill_id` values
3. No "insufficient position" rejection on second order

**Evidence Criteria:**
- **Bug Present (TOCTOU):** Second order rejects with "insufficient position" because first fill not yet ledgered
- **Bug Present (Netting):** Position shows 100 (both counted as buys)
- **Bug Absent:** Both fills confirmed, position=0, PNL positive

**Critical TOCTOU Check:**
```python
# Immediately after second order submission, poll position
pos_immediate = requests.get("/positions").json()
if pos_immediate["size"] < 50:
    log("TOCTOU: Position lag detected before second fill")
```

---

### Probe C: Multiple Markets Same Event

**Exact Orders to Issue:**
```python
markets = [
    "FED-250319-RATE-HIKE-25BP",
    "FED-250319-RATE-HOLD",
    "FED-250319-RATE-CUT-25BP"
]
orders = [
    {"ticker": markets[0], "side": "yes", "action": "buy", "size": 5, "price": 30},
    {"ticker": markets[1], "side": "yes", "action": "buy", "size": 10, "price": 45},
    {"ticker": markets[2], "side": "yes", "action": "buy", "size": 3, "price": 25},
]
```

**Expected Event Sequence:**
1. All 3 orders submitted
2. 3 separate fills arrive (timing may vary)
3. `/positions` shows 3 entries, each with correct market ticker
4. `/discover-health` shows `positions_by_asset` breakdown

**Invariants to Validate:**
1. `positions.count == 3`
2. Each position ticker matches order ticker exactly (no cross-contamination)
3. `positions_by_asset` aggregates by underlying asset (FED-RATE-DECISION-2025-03-19)
4. Total exposure respects event-level limits (if configured)

**Evidence Criteria:**
- **Bug Present:** Position from market A appears under market B ticker
- **Bug Present:** `positions_by_asset` double-counts (shows 18 instead of 18 total but wrong breakdown)
- **Bug Absent:** All 3 positions tracked independently, correct aggregation

---

### Probe D: Partial Fill → Amend → Complete

**Exact Orders to Issue:**
```python
# Order 1: Initial order
initial_order = {
    "ticker": "ETH-250330-PUT-1800",
    "side": "yes",
    "action": "buy",
    "size": 20,
    "price": 40,
    "type": "limit"
}
# Wait for partial fill

# Order 2: Amendment (price change)
amendment = {
    "order_id": "ORD-001",  # From initial
    "new_price": 42,
    "remaining_size": 12  # 20 - 8 filled
}
# POST /orders/{id}/amend
```

**Expected Event Sequence:**
1. T+0s: Initial order live
2. T+5s: Partial fill: +8 @ 40¢ (fill_id=FILL-A)
3. T+6s: Order status = `partially_filled`, remaining=12
4. T+10s: Amendment submitted
5. T+11s: Amendment confirmed (Kalshi may return new order_id or keep same)
6. T+15s: Remaining 12 fill @ 42¢ (fill_id=FILL-B)
7. T+16s: Position = +20, avg price = (8×40 + 12×42)/20 = 41.2¢

**Invariants to Validate:**
1. Two fills with distinct `fill_id` values, both linked to same `order_id`
2. Position size = 20 (not 8, not 12)
3. Avg price calculation uses actual fill prices, not amended price

**Evidence Criteria:**
- **Bug Present:** Only 8 contracts in position (amend created orphan order)
- **Bug Present:** Avg price = 42¢ (used amended price, not actual fills)
- **Bug Absent:** Both fills attributed, correct avg price, order lineage tracked

---

### Probe E: WebSocket Fill During HTTP Poll Gap

**Setup:**
```python
# Configure poller
POLL_INTERVAL = 30  # seconds

# Start WebSocket listener
ws = KalshiWebSocketClient()
ws.subscribe_fills()

# At T=0, note last HTTP poll cursor
baseline_cursor = poller.cursor
```

**Exact Test Sequence:**
1. T=0: HTTP poll completes, records cursor
2. T=5s: Submit order via API, wait for fill
3. T=6s: WebSocket receives fill notification (immediate)
4. T=6s: Ledger updated via WS path
5. T=10s: Query `/positions` — should show new position
6. T=30s: Next HTTP poll — includes T=5s fill in response
7. T=30s: Ledger must deduplicate (already has this fill from WS)

**Invariants to Validate:**
1. Position at T=10s reflects new fill (WS path works)
2. Ledger at T=30s has exactly 1 entry for the fill (HTTP didn't duplicate)
3. `fill_id` appears in ledger logs exactly once ("add_fill" called once)

**Evidence Criteria:**
- **Bug Present (TOCTOU):** Position at T=10s doesn't show new fill (WS not updating ledger)
- **Bug Present (Duplicate):** Ledger shows 2 entries for same `fill_id` (WS and HTTP both added)
- **Bug Absent:** Single ledger entry, position updated via WS, HTTP poll sees already-present fill

**Log Traces Needed:**
```
# Expected log sequence
T+6s  [WS] Received fill: fill_id=FILL-WS-001
T+6s  [LEDGER] add_fill: fill_id=FILL-WS-001, result=NEW
T+30s [POLLER] HTTP poll returned 1 fill: fill_id=FILL-WS-001
T+30s [LEDGER] add_fill: fill_id=FILL-WS-001, result=DUPLICATE (skipped)
```

---

## 3. Fills Ledger Probes — Instrumentation & Validation

### Probe L1: Uniqueness on `fill_id`

**Method:**
```python
# Synthetic injection test
def test_fill_uniqueness():
    ledger = get_fills_ledger()
    
    # Create synthetic fill
    fill = SyntheticFill(
        fill_id="TEST-UNIQUE-001",
        ticker="TEST-BTC",
        side="yes",
        size=5,
        price=50,
        timestamp=datetime.now(timezone.utc)
    )
    
    # First add
    result1 = ledger.add_fill(fill)
    count1 = len(ledger._fills)
    
    # Duplicate add
    result2 = ledger.add_fill(fill)
    count2 = len(ledger._fills)
    
    # Assertions
    assert result1 == True, "First add should succeed"
    assert result2 == False, "Duplicate add should be rejected"
    assert count1 == count2, "Count should not increase on duplicate"
    assert "TEST-UNIQUE-001" in ledger._fill_ids
```

**Observable:**
- Log line: `add_fill: fill_id=TEST-UNIQUE-001, result=NEW`
- Log line: `add_fill: fill_id=TEST-UNIQUE-001, result=DUPLICATE`
- Ledger count stable across duplicate attempts

**Status:** INCONCLUSIVE (needs live run)

---

### Probe L2: Correct Sign Convention

**Method:**
```python
def test_sign_convention():
    ledger = get_fills_ledger()
    
    # BUY YES 10
    buy = SyntheticFill(fill_id="B-001", side="yes", action="buy", size=10, price=50)
    ledger.add_fill(buy)
    pos_buy = ledger.get_position("TEST-BTC")
    
    # SELL YES 10 (close)
    sell = SyntheticFill(fill_id="S-001", side="yes", action="sell", size=10, price=55)
    ledger.add_fill(sell)
    pos_sell = ledger.get_position("TEST-BTC")
    
    # Assertions
    assert pos_buy.size == 10, f"Expected +10, got {pos_buy.size}"
    assert pos_sell.size == 0, f"Expected 0, got {pos_sell.size}"
```

**Observable:**
- Position size after buy: +10
- Position size after sell: 0
- No negative position (would indicate sign flip)

**Status:** INCONCLUSIVE (needs live run)

---

### Probe L3: Fee Units and Application

**Method:**
```python
def test_fee_calculation():
    ledger = get_fills_ledger()
    
    fill = SyntheticFill(
        fill_id="FEE-001",
        ticker="TEST",
        side="yes",
        size=100,
        price=50,  # 50 cents = $0.50
        fee=None  # Let ledger calculate
    )
    
    ledger.add_fill(fill)
    stored_fill = ledger.get_fill("FEE-001")
    
    # Kalshi fee: 0.9% per contract, taker fee
    expected_fee = 100 * 0.50 * 0.009  # $0.45
    
    assert abs(stored_fill.fee - expected_fee) < 0.01, \
        f"Fee mismatch: expected {expected_fee}, got {stored_fill.fee}"
```

**Observable:**
- Fee in dollars (not cents): ~$0.45
- Not $45 (100x error)
- Not $0.0045 (0.01x error)

**Status:** INCONCLUSIVE (needs live run)

---

### Probe L4: Timestamp Ordering

**Method:**
```python
def test_timestamp_ordering():
    ledger = get_fills_ledger()
    
    # Create fills with same timestamp but different IDs
    base_time = datetime.now(timezone.utc)
    fills = [
        SyntheticFill(fill_id="T-003", timestamp=base_time + timedelta(seconds=2)),
        SyntheticFill(fill_id="T-001", timestamp=base_time),  # Earliest
        SyntheticFill(fill_id="T-002", timestamp=base_time + timedelta(seconds=1)),
    ]
    
    # Add out of order
    for f in fills:
        ledger.add_fill(f)
    
    # Retrieve ordered
    ordered = ledger.get_fills_ordered()
    ids = [f.fill_id for f in ordered]
    
    assert ids == ["T-001", "T-002", "T-003"], f"Wrong order: {ids}"
```

**Observable:**
- Ledger retrieval returns fills sorted by timestamp
- PNL calculations use chronological order

**Status:** INCONCLUSIVE (needs live run)

---

### Probe L5: Reconnect Recovery

**Method:**
```python
async def test_reconnect_recovery():
    # 1. Start poller, let it run for 1 minute
    poller = get_fills_poller()
    await poller.start()
    await asyncio.sleep(60)
    
    # 2. Record cursor and stop
    cursor_before = poller.cursor
    await poller.stop()
    
    # 3. Submit order while poller down
    order = submit_order(ticker="TEST", size=5)
    await asyncio.sleep(5)  # Wait for fill
    
    # 4. Restart poller
    await poller.start()
    await asyncio.sleep(30)  # Wait for poll cycle
    
    # 5. Verify fill captured
    ledger = get_fills_ledger()
    fill = ledger.get_fill_by_order_id(order.id)
    
    assert fill is not None, "Fill lost during reconnect"
    assert poller.cursor != cursor_before, "Cursor didn't advance"
```

**Observable:**
- Fill submitted during downtime appears in ledger
- Cursor advances correctly
- No gap in fill sequence

**Status:** INCONCLUSIVE (needs live run, requires manual intervention)

---

## 4. Fills Poller Probes — Instrumentation & Validation

### Probe P1: 105-Fills Pagination Case

**Method:**
```python
async def test_pagination_gap():
    poller = get_fills_poller()
    
    # Rapidly generate 150 fills (via test harness or automation)
    for i in range(150):
        submit_small_order(ticker="TEST", size=1)
        await asyncio.sleep(0.1)  # 100ms spacing
    
    # Wait for poller to run
    await asyncio.sleep(35)
    
    # Check ledger
    ledger = get_fills_ledger()
    fill_count = len(ledger._fills)
    
    # Check logs for page limit warning
    logs = get_logs("fills_poller")
    warning_count = logs.count("Hit page limit")
    
    assert fill_count == 150, f"Missing fills: expected 150, got {fill_count}"
    assert warning_count > 0, "Should have logged page limit warning"
```

**Observable:**
- Log: `Poll N: Hit page limit, possible dropped fills`
- Ledger count = 150 (not 100, not 101)

**Status:** NOT TESTED (requires high-throughput test setup)

---

### Probe P2: Cursor Rewind on Restart

**Method:**
```python
async def test_cursor_rewind():
    poller = get_fills_poller()
    
    # Accumulate 50 fills
    for _ in range(50):
        submit_order(ticker="TEST", size=1)
    await asyncio.sleep(35)
    
    # Record state
    ledger_before = len(get_fills_ledger()._fills)
    
    # Stop and rewind cursor (simulated)
    await poller.stop()
    poller.cursor = poller.cursor - 10  # Rewind 10 fills
    
    # Restart
    await poller.start()
    await asyncio.sleep(35)
    
    # Check
    ledger_after = len(get_fills_ledger()._fills)
    duplicate_warnings = get_logs().count("Duplicate fill_id")
    
    assert ledger_after == ledger_before, f"Ledger grew: {ledger_after} vs {ledger_before}"
    assert duplicate_warnings >= 10, "Should have detected 10 duplicates"
```

**Observable:**
- Log: `Duplicate fill_id: FILL-XXX` (10 times)
- Ledger count stable (deduplication working)

**Status:** INCONCLUSIVE (needs live run)

---

### Probe P3: TOCTOU During Batch Write

**Method:**
```python
async def test_toctou_batch():
    poller = get_fills_poller()
    
    # Trigger batch of 10 fills
    orders = [submit_order(ticker="TEST", size=1) for _ in range(10)]
    
    # Immediately after submission, query position rapidly
    positions = []
    for _ in range(20):  # Query 20 times over 2 seconds
        pos = requests.get("/positions").json()
        positions.append((time.time(), pos["size"]))
        await asyncio.sleep(0.1)
    
    # Analyze position progression
    sizes = [p[1] for p in positions]
    
    # Should show progression: 0 → 1 → 2 → ... → 10
    # Should NOT show: 0 → 10 → 5 → 10 (jitter indicates inconsistent reads)
    
    assert sizes[-1] == 10, "Final position wrong"
    assert all(sizes[i] <= sizes[i+1] for i in range(len(sizes)-1)), \
        f"Position decreased during batch: {sizes}"
```

**Observable:**
- Position monotonically increases during batch
- No decrements or oscillation

**Status:** INCONCLUSIVE (needs live run)

---

### Probe P4: WebSocket vs HTTP Collision

**Method:**
```python
async def test_ws_http_collision():
    # Start both WS and HTTP poller
    ws = KalshiWebSocketClient()
    ws.subscribe_fills()
    
    poller = get_fills_poller()
    await poller.start()
    
    # Submit order
    order = submit_order(ticker="TEST", size=5)
    
    # Wait for both paths
    await asyncio.sleep(5)
    
    # Check logs
    logs = get_logs("fills_ledger")
    adds = [l for l in logs if "add_fill" in l and order.id in l]
    
    # Should see exactly 1 successful add, 1 duplicate rejection
    new_adds = [l for l in adds if "result=NEW" in l]
    dup_adds = [l for l in adds if "result=DUPLICATE" in l]
    
    assert len(new_adds) == 1, f"Expected 1 NEW, got {len(new_adds)}"
    assert len(dup_adds) == 1, f"Expected 1 DUPLICATE, got {len(dup_adds)}"
```

**Observable:**
- One `add_fill: result=NEW`
- One `add_fill: result=DUPLICATE`
- Ledger has exactly 1 entry

**Status:** INCONCLUSIVE (needs live run)

---

## 5. Endpoint Contracts — Validation Results

### Contract C1: /fills Default 24h Window

**Test:**
```bash
# Call without since param
curl -s /api/v1/kalshi/fills | jq '.meta.since_hours'

# Call with explicit 168h (7 days)
curl -s "/api/v1/kalshi/fills?since_hours=168" | jq '.count'
```

**Expected:**
- Without param: returns ~24h of fills (count lower if little activity)
- With param: returns more fills (if activity existed)

**Risk:** If MERID assumes all history, historical PNL wrong

**Status:** NOT TESTED

---

### Contract C2: /fills Sort Order

**Test:**
```bash
curl -s "/api/v1/kalshi/fills?limit=5" | jq '.fills[].timestamp'
```

**Expected:** Descending (newest first) for UI "recent fills"

**Bug:** If ascending, UI shows oldest as "recent"

**Status:** NOT TESTED

---

### Contract C3: Position vs Fills Reconstruction

**Test:**
```python
# Get positions
positions = requests.get("/positions").json()["positions"]

# For each position, sum fills
for pos in positions:
    fills = requests.get(f"/fills?ticker={pos['ticker']}").json()["fills"]
    sum_size = sum(f["size"] if f["side"] == "yes" else -f["size"] for f in fills)
    
    assert pos["size"] == sum_size, \
        f"Position mismatch: {pos['ticker']} pos={pos['size']} fills_sum={sum_size}"
```

**Invariant:** `sum(fills) = position.size`

**Status:** NOT TESTED

---

### Contract C4: Orders State Machine

**Test Sequence:**
```python
# 1. Create
resp = post("/orders", order_data)
assert resp["status"] == "created"
order_id = resp["order_id"]

# 2. Poll until filled
for _ in range(30):
    status = get(f"/orders/{order_id}").json()["status"]
    if status == "filled":
        break
    time.sleep(1)
assert status == "filled"

# 3. Verify no invalid transitions
invalid = ["created" → "canceled" → "live"]  # Shouldn't happen
```

**Status:** NOT TESTED

---

## 6. Cross-Layer Invariants — Applied

| # | Invariant | Test Method | Violation Seen? | Root Cause | Evidence |
|---|-----------|-------------|-----------------|------------|----------|
| 1 | `sum(fills.size) = position.size` | Probe C3 | Not tested | — | — |
| 2 | `fill.timestamp >= order.created_at` | Log analysis | Not tested | — | — |
| 3 | `realized_pnl = sum(closed_fill_pnl)` | Probe A PNL calc | Not tested | — | — |
| 4 | `order.status ∈ valid_states` | Contract C4 | Not tested | — | — |
| 5 | `portfolio.total_value = cash + sum(positions)` | Cross-foot check | Not tested | — | — |
| 6 | `fills_complete > 0 → portfolio_empty = false` | Discover-health flag | **VERIFIED** | `kalshi_api.py` line ~1105 | `/discover-health` returns correct flag |

**Residual Risk:** All invariants except #6 remain untested under real Kalshi API load.

---

## 7. Wiring Verdict & Patch List

### Verdict Table

| Probe/Scenario | Status | Suspected Root Cause | Fix Type |
|----------------|--------|---------------------|----------|
| Probe A: Single YES buy → close | NOT TESTED | — | — |
| Probe B: Fast flip TOCTOU | NOT TESTED | `fills_ledger.py` locking | Add `threading.RLock` |
| Probe C: Multi-market cross-contamination | NOT TESTED | `kalshi_ticker_to_asset()` mapping | Validate ticker parsing |
| Probe D: Amend lineage | NOT TESTED | Order ID tracking in `kalshi_api.py` | Track amendment chain |
| Probe E: WS/HTTP dedup | NOT TESTED | `fills_ledger.py` `_fill_ids` set | Verify set membership |
| L1: Fill uniqueness | INCONCLUSIVE | — | Add `result=NEW|DUPLICATE` logging |
| L2: Sign convention | INCONCLUSIVE | — | Add position trace logging |
| L3: Fee calculation | INCONCLUSIVE | `_ledger_fill_price_usd()` | Add fee validation test |
| P1: Pagination gaps | NOT TESTED | `fills_poller.py` cursor handling | Implement `next_cursor` following |
| P2: Cursor rewind | INCONCLUSIVE | — | Add cursor continuity check |
| P3: TOCTOU batch | INCONCLUSIVE | — | Add atomic batch writes |
| P4: WS/HTTP collision | INCONCLUSIVE | — | Verify thread safety |
| C1: /fills 24h default | NOT TESTED | `kalshi_api.py` param handling | Explicit `since` param |
| C2: Sort order | NOT TESTED | — | Client-side sort |
| C3: Position reconstruction | NOT TESTED | — | Daily reconciliation job |

### Prioritized Patch List (Top 5)

| Priority | Patch | Must Fix Before Scale? | Implementation |
|----------|-------|----------------------|----------------|
| 1 | **Add `threading.RLock` to `fills_ledger.py`** | YES | `self._lock = threading.RLock()` around `_fills` append and `_fill_ids` add |
| 2 | **Implement HTTP pagination following** | YES | In `fills_poller.py`: while `next_cursor`, fetch next page |
| 3 | **Add `fill_id` deduplication logging** | YES | Log `result=NEW|DUPLICATE` with `fill_id` and `source=WS|HTTP` |
| 4 | **Explicit `/fills?since=` param** | YES | Change default from 24h to account creation or 365 days |
| 5 | **Daily reconciliation job** | NICE TO HAVE | Cron job that verifies `sum(fills) = positions` and alerts on divergence |

### Distinguish: Must Fix vs Harden Later

**MUST FIX BEFORE SCALE:**
1. Thread safety in ledger (race condition on WS + HTTP)
2. Pagination gaps (lost fills under high throughput)
3. Deduplication visibility (can't tell if it's working)
4. Default time window (historical PNL silently wrong)

**NICE TO HARDEN LATER:**
5. Daily reconciliation (detection, not prevention)
6. Client-side sort (cosmetic, not data-loss)
7. Amendment lineage tracking (edge case: amends rare)

---

## Appendix: Current Code State Checklist

- [ ] `fills_ledger.py` has `threading.RLock` → NO (add immediately)
- [ ] `fills_poller.py` follows `next_cursor` → UNKNOWN (verify)
- [ ] `fills_ledger.py` logs `result=NEW|DUPLICATE` → UNKNOWN (verify)
- [ ] `kalshi_api.py` explicit `since` param → PARTIAL (`discover-health` has it, `/fills` needs check)
- [ ] Reconciliation job exists → NO (implement)
- [ ] WS/HTTP collision tested → NO (run Probe E)

---

**Report Status:** Ready for test execution  
**Next Action:** Execute Probes A-E with live Kalshi test credentials, populate INCONCLUSIVE/NOT TESTED cells
