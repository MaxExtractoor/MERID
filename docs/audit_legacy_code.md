# Legacy Code Audit

**Date:** 2026-04-18  
**Scope:** WS bridge, pipeline actions, async event loop handling  
**Production Status:** Full prod, live trading  

---

## 1. WebSocket Bridge (`merid/event_venues/kalshi/ws_bridge.py`)

### Dead/Legacy Branches
- **Line 391**: `_subscribe_warned` flag - only logs warning once, but no recovery mechanism
- **Lines 286-312**: `_task_done_cb` - complex crash handling that may mask root causes

### Unused Parameters
- `KalshiWebSocketBridge.__init__` accepts `ws` and `config` but always creates fresh instances in practice

### Blocking I/O in Async Paths
| Location | Issue | Severity |
|----------|-------|----------|
| `_handle_kalshi_user_fill()` | Sync regex matching on hot path | Low |
| `_enqueue_event()` | Dictionary operations on bounded queue | Low |

### CPU-Heavy Sections
- **UI coalescing loop** (lines 327-331): Batches UI updates every 100ms, but does not yield during batch processing

---

## 2. Pipeline Actions (`merid/loop.py`)

### Dead/Legacy Branches
- **Line 552-557**: `betting_refresh` feature flag check - disabled by default, never enabled in prod
- **Line 2056-2071**: HashtagMonitor initialization - skipped in VALIDATION_MODE via env check

### Commented-Out Code
- None identified in critical paths

### Blocking I/O in Async Paths
| Location | Issue | Severity |
|----------|-------|----------|
| `_refresh_liquidity()` | Thread pool offload exists but no timeout on `og_lifecycle.start()` | HIGH |
| `_sync_order_groups()` | `og_lifecycle.start()` can block indefinitely | HIGH |
| `_run_consensus()` | Debate processing offloaded but no timeout guard | Medium |

### CPU-Heavy Sections
| Location | Issue | Mitigation |
|----------|-------|------------|
| `_run_arb_scan()` | Signal scanning loops over all agents | Offloaded to thread pool, but no yield points inside loop |
| `_refresh_features()` | Feature service calls (news/social/onchain) | Offloaded to thread pool with 2s timeout |
| `_run_consensus()` | Opinion pruning and aggregation | Offloaded to thread pool |

---

## 3. WebSocket Client (`merid/event_venues/kalshi/ws.py`)

### Dead/Legacy Branches
- **Lines 768-780**: `_BACKOFF_ERROR_CODES` handling for `rate_limited` - schedules backoff pause but doesn't prevent concurrent reconnect attempts
- **Lines 861-893**: Lag pause mode - complex state machine that may not exit cleanly

### Unused Parameters
- `_drop_lowest_priority()` - `msg_priority` param used but priority classification is basic (only 2 levels)

### Blocking I/O in Async Paths
| Location | Issue | Severity |
|----------|-------|----------|
| `connect()` | RSA key loading from filesystem | Medium (cached after first load) |
| `subscribe_*()` methods | Sync set operations on subscription tracking | Low |

### CPU-Heavy Sections
- **Message parsing** (`_parse_message()`): JSON decode + object creation on every message
- **Sequence checking** (`_check_sequence()`): Dict lookups per message

---

## 4. Global Issues

### Thread Pool Saturation Risk
- `_get_loop_executor()` creates 32-worker pool
- Multiple actions submit work concurrently: `liquidity`, `arb_scan`, `order_groups`, `consensus`
- Under heavy load, queue buildup can cause cascading delays

### Async Event Loop Yield Points Missing
| Location | Impact |
|----------|--------|
| `arb_scan` signal loop | Can block for seconds without yielding |
| `liquidity` orderbook processing | Offloaded to thread, but main loop waits with `await` |
| `order_groups` lifecycle start | No explicit yield during startup |

### Environment Variable Proliferation
| Variable | Risk |
|----------|------|
| `KALSHI_WS_RECONNECT_LAG_THRESHOLD_MS` | May be set too high (1000ms default) |
| `MERID_LOOP_SLOW_ACTION_BUDGET_MS` | Soft budget only, no hard enforcement |
| `MERID_VALIDATION_MODE` | Used to skip features, could hide issues |

---

## Recommended Removals (Post-Hardening)

1. **Remove `betting_refresh` feature flag** (line 552-557) - permanently disable dead code path
2. **Remove `_subscribe_warned` singleton pattern** - replace with rate-limited logging
3. **Remove lag pause mode complexity** (lines 861-893) - replace with simpler backoff

---

## Async Safety Gaps

### GAP-1: No timeout on `og_lifecycle.start()`
**Location:** `loop.py:1908`  
**Risk:** Can hang indefinitely, blocking tick  
**Fix:** Add `asyncio.wait_for()` with 5s timeout

### GAP-2: `arb_scan` loop lacks yield points
**Location:** `kalshi_continuous_trader.py` signal scanning  
**Risk:** CPU-bound loop blocks event loop  
**Fix:** Insert `await asyncio.sleep(0)` every N iterations

### GAP-3: WS subscribe batching doesn't yield between batches
**Location:** `ws_bridge.py:255-273`  
**Risk:** Large ticker lists block loop during startup  
**Fix:** Verify `_stagger_delay = 0.01` is actually yielding (it is, but verify effective)
