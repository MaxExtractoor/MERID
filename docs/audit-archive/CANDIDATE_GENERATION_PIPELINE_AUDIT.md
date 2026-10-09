# Candidate Generation Pipeline Audit Report

**Date:** 2026-06-24
**Issue:** Thousands of orderbook events processed, zero candidates generated
**Scope:** Full pipeline from WebSocket events to candidate generation

## Executive Summary

The system is receiving thousands of orderbook_delta events across all 5 assets (BTC, ETH, SOL, XRP, DOGE) but generating zero candidates. This indicates a critical disconnect between the WebSocket event layer and the candidate generation layer.

## Pipeline Layers

### Layer 1: WebSocket Event Reception
**File:** `merid/event_venues/kalshi/ws_bridge.py`
**Status:** ✅ Working (receiving events)

**Evidence:**
- Logs show: `[WS-FORWARDER-WRITE] ticker=KXBTC15M-26JUN240200-00 event_type=orderbook_delta seq=197452`
- Thousands of events processed across all 5 assets
- WebSocket connection stable and receiving data

**Process:**
1. Kalshi WS sends `orderbook_delta` messages
2. Bridge receives and enqueues events
3. Forwarder loop processes events from queue
4. Calls `store.apply_orderbook_message(msg_body, "bridge_queue")`

**Issue Identified:**
- Logs show: `[WS-APPLY] UNKNOWN type=orderbook_delta`
- This suggests the event type is not being recognized properly
- May indicate schema mismatch or parsing issue

### Layer 2: Market State Store
**File:** `merid/event_venues/kalshi/market_state.py`
**Status:** ⚠️ Suspected Issue (not populating bid/ask)

**Expected Behavior:**
- `apply_orderbook_message()` should parse WS messages
- Update `LocalOrderbook` with bid/ask data
- Sync `KalshiMarketState` with `best_bid_cents` and `best_ask_cents`

**Evidence of Issue:**
- Agent grid validation fails with: `best_bid` and `best_ask` are None
- Market state store has `best_bid_cents` and `best_ask_cents` fields in `MarketQuote`
- These fields should be populated from orderbook data

**Potential Root Causes:**
1. WS message schema mismatch - bridge not parsing correctly
2. Orderbook parsing logic not extracting bid/ask from delta messages
3. State sync logic not updating `best_bid_cents`/`best_ask_cents` from orderbook
4. Market state not being properly initialized with REST snapshot before WS deltas

### Layer 3: Agent Grid Market Validation
**File:** `merid/prediction/agent_grid_15m.py`
**Status:** ❌ Failing (market state validation)

**Process:**
1. `collect_order_candidate()` called for each agent
2. Gets spot price from unified_spot_service ✅ Working
3. Gets market from catalog ✅ Working
4. Calls `_validate_market_state(market)` ❌ Failing here
5. Validation checks:
   - Market presence ✅
   - Staleness ✅
   - Depth (yes/no) ✅
   - **Spread (bid/ask) ❌ FAILING - best_bid and best_ask are None**

**Code Location:**
```python
# Line 243-254 in agent_grid_15m.py
best_bid = getattr(market_state, 'best_bid_cents', 0)
best_ask = getattr(market_state, 'best_ask_cents', 0)
# Handle None values - treat as missing data
if best_bid is None or best_ask is None:
    logger.warning("[MARKET-VALIDATION] asset=%s ticker=%s missing bid/ask for spread check bid=%s ask=%s",
                 self.config.name, ticker, best_bid, best_ask)
    return False
```

**Result:** No candidates generated because market state lacks bid/ask data

### Layer 4: Signal Generation
**File:** `merid/prediction/agent_grid_15m.py`
**Status:** ⚠️ Not reached (blocked by validation)

**Expected Behavior:**
- `_generate_signal()` uses Coinbase velocity for trade direction
- Calculates edge, confidence, model_prob
- Returns signal dict with side, action, edge_pct, confidence, model_prob

**Status:** Never reached because validation fails first

### Layer 5: Candidate Construction
**File:** `merid/prediction/agent_grid_15m.py`
**Status:** ⚠️ Not reached (blocked by validation)

**Expected Behavior:**
- Construct candidate dict with all required fields
- Update cooldown and strip order counts
- Return candidate to order router

**Status:** Never reached because validation fails first

## Critical Disconnects

### Disconnect #1: WS Events → Market State Store
**Problem:** Orderbook_delta events received but not populating bid/ask in market state

**Evidence:**
- Thousands of WS events processed
- Logs show "UNKNOWN type=orderbook_delta"
- Market state has None for best_bid_cents/best_ask_cents

**Root Cause Hypothesis:**
1. WS message schema mismatch - Kalshi changed message format
2. `apply_orderbook_message()` not parsing delta messages correctly
3. Orderbook to bid/ask extraction logic broken
4. REST snapshot bootstrap not happening before WS deltas

**Investigation Needed:**
- Check WS message schema vs expected schema
- Verify `apply_orderbook_message()` delta parsing logic
- Check if REST snapshot bootstrap is called
- Verify orderbook field mapping to best_bid_cents/best_ask_cents

### Disconnect #2: Market State Store → Agent Grid
**Problem:** Agent grid reading from market state but getting None values

**Evidence:**
- Agent grid calls `getattr(market_state, 'best_bid_cents', 0)`
- Returns None instead of integer
- Validation fails immediately

**Root Cause Hypothesis:**
1. Market state object structure mismatch
2. Field name mismatch (best_bid_cents vs something else)
3. Market state not being updated after WS events
4. Wrong market state object being passed to agent

**Investigation Needed:**
- Verify market state object structure
- Check field names in KalshiMarketState
- Verify market state is being updated by WS bridge
- Check if agent is receiving correct market state object

## Components Involved

### WebSocket Layer
- `merid/event_venues/kalshi/ws_bridge.py` - WS connection and event forwarding
- `merid/event_venues/kalshi/ws_event.py` - WS message parsing
- `merid/event_venues/kalshi/kalshi_websocket.py` - Kalshi WS client

### Market State Layer
- `merid/event_venues/kalshi/market_state.py` - Market state store
- `merid/event_venues/kalshi/models.py` - KalshiMarketState dataclass
- `merid/event_venues/kalshi/orderbook.py` - LocalOrderbook

### Agent Layer
- `merid/prediction/agent_grid_15m.py` - Agent grid and candidate generation
- `merid/prediction/agent_grid_config.py` - Agent configuration

### Data Layer
- `merid/event_venues/kalshi/market_catalog.py` - Market catalog
- `data/unified_spot_service.py` - Spot price provider

## Next Steps

### Immediate Investigation
1. **Check WS message schema:**
   - Log raw WS message body for orderbook_delta
   - Compare with expected schema in ws_event.py
   - Verify field names match

2. **Check market state update logic:**
   - Add logging in `apply_orderbook_message()` to show what's being parsed
   - Verify orderbook fields are being extracted
   - Check if best_bid_cents/best_ask_cents are being set

3. **Check REST bootstrap:**
   - Verify REST snapshot is called before WS deltas
   - Check if bootstrap populates bid/ask
   - Verify bootstrap success logs

4. **Check agent grid market state access:**
   - Log market state object structure
   - Verify field names match
   - Check if correct market state object is passed

### Hypothesis Testing
1. **Hypothesis 1:** WS message schema changed
   - Test: Log raw WS message and compare with expected schema
   - Fix: Update ws_event.py parsing logic

2. **Hypothesis 2:** Orderbook parsing broken
   - Test: Add logging in apply_orderbook_message to show parsed fields
   - Fix: Update orderbook extraction logic

3. **Hypothesis 3:** REST bootstrap not happening
   - Test: Check logs for REST snapshot bootstrap
   - Fix: Ensure bootstrap is called before WS subscription

4. **Hypothesis 4:** Field name mismatch
   - Test: Log market state object structure
   - Fix: Update agent grid to use correct field names

## Required Fixes

### Fix #1: Add Diagnostic Logging
Add detailed logging at each layer to trace data flow:
- WS bridge: Log raw message body for orderbook_delta
- Market state: Log parsed fields in apply_orderbook_message
- Agent grid: Log market state object structure

### Fix #2: Verify WS Message Schema
Check if Kalshi changed orderbook_delta message format:
- Compare actual WS messages with expected schema
- Update ws_event.py if schema changed
- Test with sample messages

### Fix #3: Fix Orderbook Parsing
Ensure orderbook_delta messages populate bid/ask:
- Verify delta message parsing logic
- Check field extraction from orderbook
- Ensure best_bid_cents/best_ask_cents are set

### Fix #4: Ensure REST Bootstrap
Verify REST snapshot bootstrap happens before WS deltas:
- Check bootstrap call in ws_bridge startup
- Verify bootstrap populates initial bid/ask
- Ensure bootstrap completes before WS subscription

### Fix #5: Fix Agent Grid Field Access
Verify agent grid uses correct field names:
- Check KalshiMarketState structure
- Verify field names match agent expectations
- Update agent grid if field names changed

## Success Criteria

1. WS orderbook_delta events properly parsed
2. Market state store populated with best_bid_cents/best_ask_cents
3. Agent grid validation passes with valid bid/ask
4. Candidates generated for all 5 assets
5. Orders submitted to Kalshi

## Timeline

- **Phase 1:** Add diagnostic logging (30 min)
- **Phase 2:** Identify root cause (30 min)
- **Phase 3:** Implement fix (1 hour)
- **Phase 4:** Test and verify (30 min)

Total estimated time: 2.5 hours
