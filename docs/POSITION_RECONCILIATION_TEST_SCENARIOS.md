# Position Reconciliation Test Scenarios

## Overview
These test scenarios verify that local position state (`KalshiPositionCache`) correctly matches Kalshi's actual positions (`client.get_positions()`) under various failure conditions.

## Test Environment Setup
- Kalshi paper trading account
- Server running with `MERID_PROFILE=kalshi_crypto_15m_v2`
- Monitoring logs for `[POSITION-CACHE]`, `[RECONCILIATION]`, `[FILLS-LEDGER]`
- Access to Kalshi dashboard for ground truth verification

---

## Scenario 1: Normal Fill Reconciliation

**Purpose:** Verify position cache updates correctly on successful fills

**Steps:**
1. Start server with zero positions
2. Place small YES order via UI (e.g., 1 contract on BTC market)
3. Monitor logs for fill notification
4. Check `KalshiPositionCache.get_position(ticker)` immediately after fill
5. Verify against Kalshi dashboard position

**Expected Results:**
- `[FILLS-LEDGER]` logs fill receipt
- `[POSITION-CACHE]` updates position count
- Local cache matches Kalshi dashboard within 5 seconds
- No reconciliation warnings in logs

**Failure Indicators:**
- Position count mismatch between cache and dashboard
- Reconciliation error logged
- Position not updated in cache after 30 seconds

---

## Scenario 2: WebSocket Disconnection Mid-Fill

**Purpose:** Verify reconciliation after WS gap during order execution

**Steps:**
1. Start server with active WebSocket connection
2. Place order via UI
3. **Kill WebSocket connection** during fill processing (e.g., `netstat` kill or firewall block)
4. Wait 10 seconds for WS reconnection
5. Check position cache state
6. Verify against Kalshi dashboard

**Expected Results:**
- WS reconnection triggers reconciliation
- `[POSITION-CACHE]` logs "Syncing from REST API after WS gap"
- Position cache corrects to match Kalshi dashboard
- Sequence number gap detected and logged

**Failure Indicators:**
- Position cache stale after WS reconnect
- No reconciliation triggered
- Position mismatch persists > 60 seconds

---

## Scenario 3: Partial Fill Handling

**Purpose:** Verify position cache handles partial fills correctly

**Steps:**
1. Place large order (e.g., 50 contracts) on illiquid market
2. Monitor for partial fill notifications
3. Check position cache after each partial fill
4. Verify cumulative position matches Kalshi dashboard

**Expected Results:**
- Each partial fill updates position cache incrementally
- Final position matches total filled contracts
- No duplicate position entries
- `[FILLS-LEDGER]` logs each partial fill

**Failure Indicators:**
- Position count doesn't increment with partial fills
- Duplicate position entries created
- Final position mismatch

---

## Scenario 4: Network Timeout During Position Sync

**Purpose:** Verify graceful handling of REST API timeouts

**Steps:**
1. Simulate network timeout (e.g., firewall block Kalshi API for 30s)
2. Trigger position sync (e.g., manual reconciliation call)
3. Monitor error handling
4. Restore network connectivity
5. Verify reconciliation succeeds on retry

**Expected Results:**
- Timeout logged with warning
- Position cache uses last known good state
- Reconciliation retries after network restored
- No crash or exception propagation

**Failure Indicators:**
- Unhandled exception crashes position sync
- Position cache corrupted
- No retry mechanism

---

## Scenario 5: Sequence Number Gap Detection

**Purpose:** Verify WS sequence number monitoring

**Steps:**
1. Monitor WS message sequence numbers in logs
2. Inject artificial gap (e.g., skip sequence by forcing WS reconnect)
3. Check for sequence gap detection
4. Verify reconciliation triggered

**Expected Results:**
- `[WS-BRIDGE]` logs sequence number jump
- Reconciliation automatically triggered
- Position cache synced from REST API
- Gap logged with before/after sequence numbers

**Failure Indicators:**
- Sequence gap not detected
- No reconciliation triggered
- Position cache diverges from reality

---

## Scenario 6: Concurrent Order + Reconciliation

**Purpose:** Verify no race condition between order placement and reconciliation

**Steps:**
1. Place order via UI
2. Simultaneously trigger manual reconciliation (e.g., API call)
3. Monitor for race conditions
4. Verify final position state consistent

**Expected Results:**
- Both operations complete without conflict
- Position cache ends in correct state
- No deadlock or timeout
- Logs show clear ordering of events

**Failure Indicators:**
- Deadlock between order and reconciliation
- Position cache corrupted
- Concurrent modification error

---

## Scenario 7: Stale Position Cache Detection

**Purpose:** Verify staleness threshold enforcement

**Steps:**
1. Disable position cache updates (e.g., block WS + REST)
2. Wait for staleness threshold (e.g., 5 minutes)
3. Check staleness warnings in logs
4. Re-enable updates
5. Verify reconciliation forced

**Expected Results:**
- `[POSITION-CACHE]` logs "Stale position detected"
- Trading halted if threshold exceeded
- Reconciliation forced when connectivity restored
- Staleness timestamp logged

**Failure Indicators:**
- No staleness detection
- Trading continues with stale positions
- No forced reconciliation

---

## Scenario 8: Market Expiry Position Cleanup

**Purpose:** Verify expired positions removed from cache

**Steps:**
1. Hold position in market expiring soon
2. Wait for market expiry
3. Check position cache after expiry
4. Verify position removed

**Expected Results:**
- `[POSITION-CACHE]` logs "Removing expired position"
- Position deleted from cache
- No memory leak
- Kalshi dashboard shows no position

**Failure Indicators:**
- Expired position remains in cache
- Memory leak from accumulating expired positions
- Cleanup not triggered

---

## Scenario 9: Multi-Market Position Drift

**Purpose:** Verify reconciliation across multiple markets

**Steps:**
1. Hold positions in 3+ different markets
2. Induce drift in one market (e.g., manual cancel via Kalshi dashboard)
3. Trigger reconciliation
4. Verify only drifted market corrected
5. Verify other markets unchanged

**Expected Results:**
- Reconciliation identifies specific drifted market
- Only drifted market position corrected
- Other markets remain unchanged
- Per-market reconciliation logged

**Failure Indicators:**
- All positions re-synced unnecessarily
- Drifted market not corrected
- Non-drifted markets corrupted

---

## Scenario 10: Reconciliation Loop Stress Test

**Purpose:** Verify reconciliation under high load

**Steps:**
1. Place 20 orders rapidly (e.g., script or UI automation)
2. Monitor reconciliation frequency
3. Check for performance degradation
4. Verify all positions eventually correct

**Expected Results:**
- Reconciliation keeps pace with fills
- No backlog accumulation
- All positions correct within 60 seconds
- No reconciliation failures

**Failure Indicators:**
- Reconciliation backlog grows
- Positions remain incorrect
- Reconciliation timeouts
- Performance degradation

---

## Automation Script Template

```python
import asyncio
import time
from merid.event_venues.kalshi.position_cache import get_kalshi_position_cache
from merid.event_venues.kalshi.kalshi_client import get_kalshi_client

async def test_scenario_1_normal_fill():
    """Test normal fill reconciliation"""
    cache = get_kalshi_position_cache()
    client = get_kalshi_client()
    
    # Get initial position
    ticker = "KXBTC15M-26MAY221100-00"
    initial_pos = cache.get_position(ticker)
    print(f"Initial position: {initial_pos}")
    
    # Place order (manual step - use UI or API)
    print("Place order via UI now...")
    time.sleep(10)
    
    # Check position after fill
    updated_pos = cache.get_position(ticker)
    print(f"Updated position: {updated_pos}")
    
    # Verify against Kalshi API
    api_positions = await client.get_positions()
    api_pos = next((p for p in api_positions if p['ticker'] == ticker), None)
    print(f"API position: {api_pos}")
    
    # Assert match
    assert updated_pos == api_pos['count'], f"Mismatch: cache={updated_pos}, api={api_pos['count']}"
    print("✓ Scenario 1 passed")

# Run test
asyncio.run(test_scenario_1_normal_fill())
```

---

## Log Patterns to Monitor

**Successful Reconciliation:**
```
[POSITION-CACHE] Syncing from REST API: N positions
[RECONCILIATION] Position cache synced: N positions matched
[FILLS-LEDGER] Fill received: ticker=KXBTC15M-... count=10
```

**Failure Patterns:**
```
[POSITION-CACHE] ERROR: Failed to sync from REST API
[RECONCILIATION] Mismatch detected: cache=5, api=10
[WS-BRIDGE] Sequence gap detected: 100 -> 150
[POSITION-CACHE] Stale position detected: age=600s
```

---

## Success Criteria

All scenarios pass if:
- Position cache matches Kalshi dashboard within 30 seconds
- No unhandled exceptions during reconciliation
- Staleness detected and logged appropriately
- Sequence gaps trigger reconciliation
- No race conditions under concurrent operations
- Performance degrades gracefully under load
