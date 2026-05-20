# Audit Step 4: Execution and Kalshi Integration

**Date:** 2026-05-12  
**Scope:** BTC/ETH/SOL/XRP/DOGE 15-minute contracts  
**Purpose:** Trace order lifecycle, verify error/retry behavior, check Kalshi-specific integration

---

## Order Lifecycle Trace

### Order Router
**File:** `merid/event_venues/kalshi/order_router.py`  
**Purpose:** Mode-aware order dispatch (mock/paper/live)  
**Caller Restrictions:** Only `merid.prediction.trading_agent` can execute trades (single executor principle)

**Lifecycle Stages:**
1. **Intent Creation** - OrderIntent created with ticker, side, action, price, count
2. **Pre-Trade Gate** - Risk checks, kill switch, trading mode validation
3. **Scope Validation** - Trading scope validation (if available)
4. **Market Filter** - Ticker validation, market closed checks
5. **Risk Parameters** - Deep OTM/ITM checks, model prob distance
6. **Execution Dispatch** - Route to appropriate execution path based on TradingMode
7. **Result Return** - OrderResult with status, order_id, fills, error

**Status:** ✅ Order lifecycle defined with caller restrictions

---

### Order Intent Structure
**Fields:**
- ticker: Kalshi market ticker (e.g., KXBTCD-25JUN-T100000)
- side: "yes" or "no"
- action: "buy" or "sell"
- price_cents: Order price in cents
- count: Contract count
- agent_id: Agent identifier
- client_tag: Optional client tag for tracking
- edge_pct: Edge percentage
- confidence: Confidence score

**Status:** ✅ Order intent structure defined

---

## Error and Retry Behavior

### Error Classification
**File:** `merid/risk/error_classification.py`  
**Purpose:** Classify errors by severity (P0-P3)

**Error Types:**
- P0: Critical - system-wide impact, requires immediate action
- P1: High - significant impact, requires action
- P2: Medium - limited impact, log and monitor
- P3: Low - cosmetic, informational only

**Status:** ✅ Error classification exists

---

### Circuit Breaker
**File:** `merid/resilience/circuit_breaker.py`  
**Purpose:** Prevent cascading failures

**States:**
- CLOSED: Normal operation
- OPEN: Failing, reject requests
- HALF_OPEN: Testing recovery

**Parameters:**
- failure_threshold: 5
- recovery_timeout: 30.0s
- half_open_max_calls: 3
- half_open_success_required: 2

**Status:** ✅ Circuit breaker implemented

---

### Retry Logic
**Finding:** Limited explicit retry logic found in codebase

**Timeouts:**
- HTTP client timeouts: 30s default
- Kalshi client timeouts: Configurable
- Order execution timeouts: 15-30s

**Backoff:** No explicit exponential backoff found

**Status:** ⚠️ Limited retry/backoff infrastructure

---

### Partial Fill Handling
**Finding:** Partial fills handled via fills ledger

**Status:** ✅ Partial fill handling exists

---

### Reject Handling
**Finding:** Rejected orders logged and tracked

**Status:** ✅ Reject handling exists

---

### Throttling
**File:** `web/api/kalshi_rate_limit.py`  
**Purpose:** Rate limiting for Kalshi API calls

**Rate Limits:** 100 requests/minute default

**Status:** ✅ Rate limiting exists

---

## Kalshi Specifics

### Request Signing
**Finding:** RSA signing for Kalshi API authentication

**File:** `merid/event_venues/kalshi/client.py`  
**Implementation:** RSA signature generation for API requests

**Status:** ✅ Request signing implemented

---

### Timestamp Usage
**Finding:** Timestamps used in API requests for authentication

**Status:** ✅ Timestamps used for authentication

---

### Idempotency
**Finding:** client_tag used for order tracking and deduplication

**Status:** ⚠️ Limited idempotency - client_tag for tracking only

---

### Logging
**Finding:** Comprehensive logging throughout order lifecycle

**Structured Block Logging:**
- Canonical block reasons via `merid.guards.block_reasons`
- Asset/timeframe extraction from ticker
- Caller module tracking
- Agent ID tracking

**Status:** ✅ Comprehensive logging

---

### Risk Enforcement
**Finding:** Multiple risk enforcement points

**Risk Gates:**
- Pre-trade gate: Kill switch, trading mode
- Scope validation: Trading scope checks
- Market filter: Ticker validation, market closed
- Risk parameters: Deep OTM/ITM, model prob distance
- Position sizing: Bankroll caps, exposure limits

**Status:** ✅ Multiple risk enforcement points

---

## Critical Findings

### 🟡 WARNING: Limited Retry/Backoff Infrastructure

**Issue:** No explicit exponential backoff for failed requests

**Impact:** Transient failures may cause order failures without retry

**Risk:** Medium - Could miss trading opportunities

**Recommendation:** Implement exponential backoff with jitter for transient failures

---

### 🟡 WARNING: Limited Idempotency

**Issue:** client_tag used for tracking but not for true idempotency (no deduplication of duplicate requests)

**Impact:** Duplicate orders could be submitted on retries

**Risk:** Medium - Could cause duplicate positions

**Recommendation:** Implement true idempotency using client_tag with deduplication

---

### 🟢 INFO: Comprehensive Risk Enforcement

**Positive:** Multiple risk enforcement points throughout order lifecycle

**Implementation:**
- Caller restrictions (single executor principle)
- Pre-trade gate (kill switch, trading mode)
- Scope validation (trading scope)
- Market filter (ticker validation, market closed)
- Risk parameters (deep OTM/ITM, model prob distance)
- Position sizing (bankroll caps, exposure limits)

---

### 🟢 INFO: Structured Block Logging

**Positive:** Canonical block reasons with structured logging

**Implementation:**
- BlockReason enum for canonical reasons
- Asset/timeframe extraction
- Caller module tracking
- Agent ID tracking
- Migration path from legacy reasons

---

## Missing Capabilities

### 1. Exponential Backoff
**Current:** Limited retry logic  
**Needed:** Exponential backoff with jitter for transient failures

---

### 2. True Idempotency
**Current:** client_tag for tracking only  
**Needed:** Deduplication of duplicate requests using client_tag

---

### 3. Order Lifecycle Tracing
**Current:** Logging at each stage  
**Needed:** End-to-end trace ID for complete order lifecycle

---

## Next Steps for Step 4

1. ✅ Identify order lifecycle - DONE
2. ✅ Identify error/retry behavior - DONE
3. ✅ Identify Kalshi specifics - DONE
4. ⏳ Sample real orders and trace lifecycle - NEED PRODUCTION DATA
5. ⏳ Test retry/backoff behavior - NEED PRODUCTION ACCESS

---

## Summary

**Obviously Broken:**
- None found in this step

**Probably Fine:**
- Order lifecycle defined with caller restrictions
- Error classification exists (P0-P3)
- Circuit breaker implemented
- Partial fill handling exists
- Reject handling exists
- Rate limiting exists
- Request signing implemented
- Timestamps used for authentication
- Comprehensive logging
- Multiple risk enforcement points
- Structured block logging

**Weird/Unclear:**
- Limited retry/backoff infrastructure (no exponential backoff)
- Limited idempotency (client_tag for tracking only, no deduplication)
- No end-to-end trace ID for complete order lifecycle
