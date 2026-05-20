# Spot Price Feed Root Cause Analysis

**Date**: 2025-01-15
**Scope**: Audit and harden spot price feed service for Kalshi crypto edge stack
**Priority**: P0 - Critical for 15m crypto trading

## Executive Summary

The spot price feed service has **5 separate components** with overlapping responsibilities and **critical correctness/stability issues** that could cause inaccurate or unstable prices for Kalshi crypto trading. The root causes span data correctness, feed stability, exchange-specific behavior, aggregation logic, and production reliability.

**Most Critical Issues (P0)**:
1. Fake bid/ask spread estimation (0.1% synthetic spread)
2. Symbol mapping chaos across 4+ formats
3. Polling-based feed instead of real-time WebSocket
4. No price validation or outlier detection
5. Weak staleness detection and monitoring

## Architecture Overview

### Current Components

| Component | File | Purpose | Status |
|-----------|------|---------|--------|
| Live Price Feed | `data/live_price_feed.py` | Original polling-based feed | Legacy, issues |
| Crypto Spot Service | `merid/trading/crypto_spot_service.py` | Unified service with 60s composite | Better, but unused |
| Kalshi Spot Adapter | `merid/trading/kalshi_crypto_spot_adapter.py` | Policy wrapper for strategies | Good design |
| WebSocket Feed | `merid/signals/ws_price_feed.py` | Coinbase real-time feed | Not integrated |
| Spot Basis Tracker | `merid/alignment/spot_basis_tracker.py` | Analytics/monitoring | Not for trading |

### Data Flow

```
┌─────────────────────────────────────────────────────────────────┐
│ Kalshi Crypto Strategies                                       │
└────────────────────────┬────────────────────────────────────────┘
                         │
                         v
┌─────────────────────────────────────────────────────────────────┐
│ KalshiCryptoSpotAdapter (policy wrapper)                       │
│ - Source quality checks                                         │
│ - Staleness handling                                            │
│ - Position sizing factor                                       │
└────────────────────────┬────────────────────────────────────────┘
                         │
                         v
┌─────────────────────────────────────────────────────────────────┐
│ CryptoSpotService (unified service)                            │
│ - Coinbase → Kraken → BinanceUS fallback                       │
│ - 60s rolling window for composite median                     │
│ - Rate limiting per source                                     │
└────────────────────────┬────────────────────────────────────────┘
                         │
                         v
┌─────────────────────────────────────────────────────────────────┐
│ Exchange APIs (REST polling)                                   │
│ - Coinbase v2 public (no auth)                                 │
│ - Kraken public ticker (no auth)                               │
│ - BinanceUS ticker (no auth)                                   │
└─────────────────────────────────────────────────────────────────┘

PARALLEL (not integrated):
┌─────────────────────────────────────────────────────────────────┐
│ Coinbase WebSocket Feed (ws_price_feed.py)                       │
│ - Real-time ticker channel                                      │
│ - Used for signal layer features ONLY                           │
│ - NOT used for trading decisions                                │
└─────────────────────────────────────────────────────────────────┘
```

## Root Cause Analysis

### 1. Data Correctness Issues (P0)

#### 1.1 Fake Bid/Ask Spread

**Location**: `data/live_price_feed.py:1501-1502`, `data/live_price_feed.py:1762-1763`

**Issue**: Coinbase public API returns only spot price, code estimates bid/ask:
```python
bid = price * 0.999  # -0.1% synthetic spread
ask = price * 1.001  # +0.1% synthetic spread
```

**Impact**: 
- Trading decisions based on fake spread data
- Position sizing calculations incorrect
- No visibility into true market liquidity

**Root Cause**: Using public endpoint instead of authenticated endpoint that returns real bid/ask.

**Evidence**:
- Coinbase Advanced Trade API returns real `best_bid` and `best_ask` (line 1158-1159)
- But public API endpoint used as fallback (line 1481)
- Same issue in CoinGecko fallback (line 1762-1763)

#### 1.2 Symbol Mapping Chaos

**Location**: Multiple files with inconsistent formats

**Issue**: 4+ different symbol formats with inconsistent conversion:

| Format | Example | Used In |
|--------|---------|---------|
| Internal | `BTC/USD` | CryptoSpotService, adapters |
| Coinbase | `BTC-USD` | live_price_feed.py |
| Kraken | `XXBTZUSD` | live_price_feed.py, crypto_spot_service.py |
| Kraken alt | `XBTUSD` | crypto_spot_service.py (line 49) |
| BinanceUS | `BTCUSD` | crypto_spot_service.py |

**Impact**:
- Mapping errors cause failed price fetches
- Inconsistent lookups across components
- Hard to debug which format is correct

**Root Cause**: No canonical symbol format; each component uses its own convention.

**Evidence**:
- `data/live_price_feed.py:1410-1416` - Coinbase mapping
- `data/live_price_feed.py:1418-1425` - Kraken mapping  
- `merid/trading/crypto_spot_service.py:40-62` - Different mappings
- Conversion happens in multiple places (line 1048, 1156, etc.)

#### 1.3 Timestamp Blindness

**Location**: `data/live_price_feed.py:1164`, `data/live_price_feed.py:1513`

**Issue**: Uses local system time instead of exchange timestamps:
```python
timestamp=datetime.now(timezone.utc)
```

**Impact**:
- No way to detect delayed/stale data from exchange
- Clock skew between system and exchanges
- Cannot measure true data latency

**Root Cause**: Not parsing exchange timestamps from API responses.

**Evidence**:
- Coinbase v3 response includes timestamp but not used
- Kraken response has no timestamp field
- All timestamps are local generation

#### 1.4 No Price Validation

**Location**: All price fetch methods

**Issue**: No validation for:
- Price reasonableness (e.g., BTC at $0.01 or $10M)
- Outlier detection (sudden 50% spike)
- Cross-source consistency checks

**Impact**:
- Bad prices can propagate through system
- No protection against data errors
- Silent failures in trading logic

**Root Cause**: No validation layer in price pipeline.

**Evidence**:
- `data/live_price_feed.py:1145-1146` - Only checks `price > 0`
- `merid/trading/crypto_spot_service.py:413` - Only checks `amount is not None`
- No cross-source comparison

### 2. Feed Stability Issues (P0)

#### 2.1 Polling Instead of WebSocket

**Location**: `data/live_price_feed.py:1042-1070`, `merid/trading/crypto_spot_service.py`

**Issue**: Main trading feed uses REST polling with 5-30s intervals instead of real-time WebSocket.

**Impact**:
- 5-30 second latency on price updates
- Missed trading opportunities
- Stale data during volatility

**Root Cause**: WebSocket feed exists but not integrated with trading decisions.

**Evidence**:
- `merid/signals/ws_price_feed.py` - Real-time WebSocket feed exists
- But only used for signal layer features, not trading
- Trading uses `CryptoSpotService.get_spot()` which polls REST APIs

#### 2.2 WebSocket Not Integrated

**Location**: Architecture gap

**Issue**: Separate WebSocket feed (`ws_price_feed.py`) not connected to main price feed.

**Impact**:
- Real-time data available but unused for trading
- Two separate data paths with different latencies
- Confusion about which feed to use

**Root Cause**: Historical development; WebSocket added later for signals only.

**Evidence**:
- `ws_price_feed.py:100-359` - Full WebSocket implementation
- `live_price_feed.py` - No WebSocket integration
- No bridge between the two components

#### 2.3 No Heartbeat Monitoring

**Location**: All polling-based feeds

**Issue**: No heartbeat mechanism to detect stale connections or silent failures.

**Impact**:
- Silent failures go undetected
- No automatic reconnection on connection drops
- Stale data served without warning

**Root Cause**: Polling-based design doesn't lend itself to heartbeat monitoring.

**Evidence**:
- No ping/pong mechanism
- No connection state tracking
- Only detects failures on next poll attempt

#### 2.4 Weak Staleness Detection

**Location**: `data/live_price_feed.py:811-849`, `merid/trading/crypto_spot_service.py:158-159`

**Issue**: Inconsistent staleness thresholds across components:

| Component | Stale Threshold | Warning Threshold |
|-----------|----------------|-------------------|
| live_price_feed.py | 120s | Not defined |
| crypto_spot_service.py | 120s | 10s (cache TTL) |
| spot_basis_tracker.py | 30s | 5s (configurable) |

**Impact**:
- Different components have different definitions of "stale"
- Trading may proceed with data other components consider stale
- Confusion about which threshold is correct

**Root Cause**: No unified staleness policy across components.

**Evidence**:
- `LIVE_FEED_HEALTH_MAX_AGE_SECONDS` constant not defined
- `SPOT_SERVICE_STALE_TTL_SECONDS` defaults to 120s
- `SPOT_STALE_MS` in spot_basis_config defaults to 30s

### 3. Exchange-Specific Issues (P1)

#### 3.1 Binance.US Incomplete

**Location**: `data/live_price_feed.py`, `merid/trading/crypto_spot_service.py`

**Issue**: Binance.US configured in `crypto_spot_service.py` but not in `live_price_feed.py`.

**Impact**:
- Inconsistent fallback behavior
- Some code paths have Binance.US, others don't
- Reduced redundancy in fallback chain

**Root Cause**: Binance.US added to crypto_spot_service but not to legacy live_price_feed.

**Evidence**:
- `crypto_spot_service.py:56-62` - BinanceUS mappings present
- `crypto_spot_service.py:529-629` - BinanceUS fetch methods present
- `live_price_feed.py` - No BinanceUS code
- User requirements mention Binance.US as required exchange

#### 3.2 Coinbase Channel Confusion

**Location**: `data/live_price_feed.py:386-447`, `data/live_price_feed.py:1130-1190`

**Issue**: Uses public v2 endpoint when Advanced Trade credentials available.

**Impact**:
- Not leveraging authenticated endpoint capabilities
- Missing real bid/ask data
- Higher rate limits on public endpoint

**Root Cause**: Fallback logic doesn't prefer authenticated endpoint.

**Evidence**:
- Line 941-999: `_connect_coinbase()` tests Advanced Trade auth
- Line 1459-1543: `_fetch_from_coinbase_public()` used as fallback
- No logic to prefer authenticated over public when both available

#### 3.3 Kraken Symbol Errors

**Location**: `data/live_price_feed.py:1410-1425`, `merid/trading/crypto_spot_service.py:48-54`

**Issue**: Inconsistent Kraken symbol formats:
- `live_price_feed.py`: Uses `XXBTZUSD`, `XETHZUSD`
- `crypto_spot_service.py`: Uses `XBTUSD`, `ETHUSD`

**Impact**:
- Mapping failures if wrong format used
- Confusion about correct format
- Potential fetch failures

**Root Cause**: No canonical Kraken symbol format.

**Evidence**:
- `live_price_feed.py:1411` - `XXBTZUSD` for BTC
- `crypto_spot_service.py:49` - `XBTUSD` for BTC
- Both are valid Kraken formats but inconsistent

### 4. Aggregation Logic Issues (P1)

#### 4.1 Inconsistent Composite Usage

**Location**: `merid/trading/crypto_spot_service.py:243-308`, `data/live_price_feed.py`

**Issue**: CryptoSpotService calculates 60s median composite but not consistently used.

**Impact**:
- Some calls use composite, others use latest single source
- Inconsistent price behavior
- Unclear which price is "correct"

**Root Cause**: Composite is optional based on data availability.

**Evidence**:
- `crypto_spot_service.py:674-676` - Uses composite if available, else single source
- `crypto_spot_service.py:692-694` - Same pattern for Kraken
- No guarantee composite is used

#### 4.2 No Outlier Rejection

**Location**: `merid/trading/crypto_spot_service.py:283-295`

**Issue**: Composite median calculated without outlier filtering.

**Impact**:
- Bad prices included in median
- One bad source can skew composite
- No protection against data errors

**Root Cause**: Simple median without filtering.

**Evidence**:
- Line 283: `prices = [p for _, p, _ in self._price_window[asset]]`
- Line 290-295: Simple median calculation
- No outlier detection or filtering

#### 4.3 No Source Confidence

**Location**: All aggregation logic

**Issue**: All sources treated equally in median, no confidence scoring.

**Impact**:
- Low-quality sources weighted same as high-quality
- No preference for primary source
- Cannot prioritize more reliable exchanges

**Root Cause**: No source confidence model.

**Evidence**:
- All prices in window treated identically
- No weighting by source quality
- No historical performance tracking

### 5. Production Reliability Issues (P1)

#### 5.1 Weak Circuit Breakers

**Location**: `data/live_price_feed.py:763-785`, `merid/trading/crypto_spot_service.py:329-358`

**Issue**: Simple failure count circuit breakers without exponential backoff.

**Impact**:
- No adaptive rate limiting
- Can overwhelm failing exchanges
- No gradual recovery

**Root Cause**: Basic circuit breaker implementation.

**Evidence**:
- `live_price_feed.py:773-775` - Simple threshold check
- `crypto_spot_service.py:329-338` - Simple error streak counter
- No exponential backoff or jitter

#### 5.2 Minimal Instrumentation

**Location**: All components

**Issue**: Limited metrics for debugging production issues.

**Impact**:
- Hard to diagnose production problems
- No visibility into feed health
- Cannot measure latency or error rates

**Root Cause**: No comprehensive metrics collection.

**Evidence**:
- `crypto_spot_service.py:183-187` - Basic failure metrics only
- No per-symbol latency tracking
- No error rate monitoring
- No structured metrics export

#### 5.3 No Structured Logging

**Location**: All components

**Issue**: Logging is unstructured, hard to parse for production debugging.

**Impact**:
- Difficult to debug production issues
- No log aggregation
- Hard to correlate events across components

**Root Cause**: No logging standard enforced.

**Evidence**:
- Mix of `logger.info`, `logger.warning`, `logger.debug`
- No structured fields (correlation IDs, request IDs)
- No consistent log format

#### 5.4 Not Fail-Safe

**Location**: All price fetch methods

**Issue**: Returns stale data instead of blocking trades when feed degraded.

**Impact**:
- Trades can execute on bad data
- No explicit "no confident price" state
- Risk of losses from bad data

**Root Cause**: Fallback logic prioritizes availability over correctness.

**Evidence**:
- All fetch methods return price or None
- No intermediate "degraded" state
- No explicit blocking on quality degradation

### 6. Testing Issues (P2)

#### 6.1 Minimal Unit Tests

**Location**: `tests/data/test_live_price_feed.py`

**Issue**: Only basic symbol mapping and initialization tests.

**Impact**:
- No coverage of price validation logic
- No coverage of staleness detection
- No coverage of aggregation logic

**Root Cause**: Test coverage not prioritized.

**Evidence**:
- 692 lines of tests, mostly basic
- No tests for price validation
- No tests for outlier detection
- No tests for composite calculation

#### 6.2 No Integration Tests

**Location**: No integration test files

**Issue**: No tests with stubbed exchange payloads.

**Impact**:
- Cannot test exchange-specific behavior
- Cannot test error scenarios
- Cannot test fallback logic

**Root Cause**: Integration tests not implemented.

**Evidence**:
- No test files with "integration" in name
- No mock exchange responses
- No end-to-end tests

#### 6.3 No Regression Tests

**Location**: No regression test files

**Issue**: No tests for known bugs or past issues.

**Impact**:
- Bugs can reoccur
- No protection against regressions
- Hard to verify fixes

**Root Cause**: Regression testing not implemented.

**Evidence**:
- No bug-specific test files
- No historical issue tracking in tests
- No regression test suite

## Recommended Fixes

### P0 Fixes (Critical)

1. **Fix fake bid/ask spread**: Remove synthetic spread estimation, use authenticated endpoints that return real bid/ask, or mark as "no spread available"
2. **Canonicalize symbol mapping**: Define single canonical format, convert at boundaries
3. **Use exchange timestamps**: Parse and validate timestamps from API responses
4. **Add price validation**: Implement reasonableness checks and outlier detection
5. **Integrate WebSocket feed**: Use real-time WebSocket for trading decisions
6. **Unify staleness thresholds**: Define single staleness policy across components

### P1 Fixes (High)

1. **Complete Binance.US integration**: Add to live_price_feed.py
2. **Prefer authenticated Coinbase endpoints**: Use Advanced Trade when credentials available
3. **Standardize Kraken symbols**: Use single format consistently
4. **Make composite mandatory**: Always use composite when sufficient data
5. **Add outlier rejection**: Filter outliers before median calculation
6. **Implement source confidence**: Weight sources by reliability
7. **Improve circuit breakers**: Add exponential backoff and jitter
8. **Add comprehensive instrumentation**: Export metrics for all key operations
9. **Implement structured logging**: Use consistent log format with correlation IDs
10. **Make fail-safe**: Block trades when feed quality degrades

### P2 Fixes (Medium)

1. **Expand unit test coverage**: Add tests for validation, staleness, aggregation
2. **Add integration tests**: Stub exchange payloads for all scenarios
3. **Add regression tests**: Test for known bugs and past issues

## Monitoring Recommendations

### Key Metrics to Track

1. **Per-source latency**: Time from fetch to return
2. **Per-source error rate**: 4xx, 5xx, timeout rates
3. **Price freshness**: Age of latest price per symbol
4. **Composite quality**: Number of sources in composite, outlier count
5. **Staleness events**: Count of stale price warnings
6. **Circuit breaker state**: Active/inactive per source
7. **Source distribution**: Percentage of prices from each source

### Alerts to Configure

1. **Stale price alert**: When any symbol > 30s stale
2. **High error rate alert**: When any source error rate > 5%
3. **Single-source composite alert**: When composite uses only one source
4. **Price outlier alert**: When price deviates > 10% from previous
5. **Circuit breaker alert**: When any circuit breaker activates

## Conclusion

The spot price feed service has fundamental issues that could lead to inaccurate or unstable prices for Kalshi crypto trading. The most critical issues are:

1. **Fake bid/ask spread** - Trading on synthetic spread data
2. **Polling instead of WebSocket** - 5-30s latency on updates
3. **No price validation** - Bad prices can propagate
4. **Symbol mapping chaos** - Mapping errors cause failures
5. **Weak staleness detection** - Inconsistent thresholds

These issues should be addressed in priority order (P0 → P1 → P2) with comprehensive testing at each stage.
