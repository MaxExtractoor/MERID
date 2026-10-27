# Kalshi API Audit - Pass 6: Structural Data Flow

**Objective:** Document single pipeline for each data type and identify structural issues.

**Kalshi Reference:** 
- [docs.kalshi.com](https://docs.kalshi.com/getting_started)
- [quantvps.com/kalshi-order-book-api-endpoints](https://www.quantvps.com/blog/kalshi-order-book-api-endpoints-explained)

---

## Current State Analysis

### 1. Orderbook Data Flow

#### Primary Pipeline (WS + REST Bootstrap)

```
Kalshi WS (orderbook_delta channel)
    ↓
ws_bridge._handle_orderbook_delta()
    ↓
market_state.apply_orderbook_message()
    ↓
LocalOrderbook (yes_levels, no_levels)
    ↓
MarketStateStore
    ↓
Agent Grid (for trading signals)
```

**Bootstrap Pipeline (REST):**
```
GET /markets/{ticker}/orderbook
    ↓
client.get_orderbook()
    ↓
_to_venue_orderbook()
    ↓
NormalizedBook (dual parsing paths)
    ↓
market_state.apply_orderbook_message()
    ↓
LocalOrderbook
    ↓
MarketStateStore
```

**Status:** ⚠️ Two parsing paths for REST bootstrap

**Issues:**
- 🚨 **Dual parsing paths:** Path 1 (raw response) vs Path 2 (VenueOrderBook)
- 🚨 **Different execution:** Thread pool vs direct call
- 🚨 **No single adapter:** Scattered parsing logic

---

### 2. Fills Data Flow

#### Primary Pipeline (WS)

```
Kalshi WS (fills channel)
    ↓
ws_bridge._handle_fills()
    ↓
fills_ledger.ingest_fill(source="websocket")
    ↓
position_cache.apply_fill()
    ↓
portfolio_engine.ingest_fill()
    ↓
PnL calculation
    ↓
Risk calculation
```

**Secondary Pipeline (REST Sync on Reconnection):**
```
GET /portfolio/fills (last 5 minutes)
    ↓
client.get_recent_fills()
    ↓
fills_ledger.ingest_fill(source="rest_reconnect_sync")
    ↓
position_cache.apply_fill()
    ↓
portfolio_engine.ingest_fill()
```

**Tertiary Pipeline (HTTP Poller - Deprecated):**
```
GET /portfolio/fills (polling)
    ↓
fills_poller._poll()
    ↓
fills_ledger.ingest_fill(source="http_poller")
    ↓
position_cache.apply_fill()
```

**Status:** ⚠️ Three ingestion paths

**Issues:**
- 🚨 **Multiple paths:** WS + REST sync + HTTP poller
- 🚨 **No continuous validation:** REST sync only on reconnection
- 🚨 **Deprecated path:** HTTP poller still exists

---

### 3. Positions Data Flow

#### Primary Pipeline (REST)

```
GET /portfolio/positions
    ↓
client.get_positions()
    ↓
position_cache.update_from_rest()
    ↓
KalshiPosition objects
    ↓
Risk calculation
    ↓
Display
```

**Secondary Pipeline (Derived from Fills):**
```
fills_ledger.get_open_exposure_usd()
    ↓
Computed net positions
    ↓
position_cache (fallback if REST empty)
    ↓
Risk calculation
```

**Status:** ⚠️ Two sources of truth

**Issues:**
- 🚨 **Dual sources:** REST positions vs fills-derived positions
- 🚨 **Fallback logic:** Uses fills if REST returns empty
- 🚨 **No validation:** Doesn't validate REST against fills

---

### 4. Bankroll Data Flow

#### Primary Pipeline (REST)

```
GET /portfolio/balance
    ↓
client.get_balance()
    ↓
bankroll_service_v2._fetch_and_update()
    ↓
BankrollResult (equity, available_cash, locked_cash)
    ↓
Risk calculation
    ↓
Position sizing
```

**Status:** ✅ Single pipeline

**Issues:**
- ⚠️ **Dual format support:** Handles flat and nested response formats
- ⚠️ **Silent correction:** Treats negative balances as zero

---

### 5. Market Discovery Data Flow

#### Primary Pipeline (REST)

```
GET /markets?series_ticker={series}
    ↓
client.list_markets_result()
    ↓
market_catalog.get_markets_for_series()
    ↓
CatalogMarket objects
    ↓
KalshiMarketCatalog
    ↓
Agent Grid (for market resolution)
```

**Status:** ⚠️ Missing series endpoint

**Issues:**
- 🚨 **No series discovery:** Doesn't use GET /series
- 🚨 **Custom filtering:** Applies custom freshness logic
- 🚨 **No startup guard:** Can run with empty catalog

---

### 6. Order Routing Data Flow

#### Primary Pipeline

```
Agent Grid / Trading Agent
    ↓
VenueOrder (market_id, side, size, price, ...)
    ↓
order_router.route_order()
    ↓
client.place_order_result()
    ↓
Global execution guard check
    ↓
Ticker validation (exists in catalog)
    ↓
Build Kalshi order payload
    ↓
POST /portfolio/orders
    ↓
Kalshi API
    ↓
PlacedOrder response
    ↓
fills_ledger (on fill)
```

**Status:** ✅ Single pipeline

**Issues:**
- ⚠️ **Multiple validation layers:** Guard + pre-send validation
- ⚠️ **Default price fallback:** Uses DEFAULT_KALSHI_PRICE_CENTS if no price

---

### 7. Ticker Resolution Data Flow

#### Primary Pipeline (Series-based)

```
Agent Grid (agent with series_tickers)
    ↓
market_selector.get_agent_market_tickers()
    ↓
KalshiMarketCatalog.get_markets_for_series()
    ↓
Series prefix match
    ↓
Live market IDs
    ↓
WS bridge subscription
```

**Secondary Pipeline (Category/Asset/Timeframe):**
```
Agent Grid (agent without series_tickers)
    ↓
_kalshi_list_markets()
    ↓
REST API with filters
    ↓
Market list
    ↓
WS bridge subscription
```

**Status:** ⚠️ Two resolution paths

**Issues:**
- 🚨 **Dual paths:** Series-based vs category-based
- 🚨 **Inconsistent:** Different resolution logic
- 🚨 **Field name mismatches:** Uses different field names

---

## Structural Issues Summary

### Issue 1: Orderbook Dual Parsing Paths

**Severity:** HIGH

**Impact:** Inconsistent orderbook data depending on which path is used

**Location:** `ws_bridge.py` (lines 390-438 vs 640-685)

**Fix:** Implement single NormalizedBook adapter

---

### Issue 2: Fills Multiple Ingestion Paths

**Severity:** HIGH

**Impact:** Potential for duplicate fills or missed fills

**Location:** `ws_bridge.py`, `fills_ledger.py`, `fills_poller.py`

**Fix:** Remove HTTP poller, add continuous REST validation

---

### Issue 3: Positions Dual Sources

**Severity:** MEDIUM

**Impact:** Inconsistent position data

**Location:** `client.py`, `fills_ledger.py`

**Fix:** Use fills ledger as single source of truth

---

### Issue 4: Bankroll Dual Format Support

**Severity:** LOW

**Impact:** May mask API errors

**Location:** `client.py` - `get_balance_result()`

**Fix:** Remove nested format support, fail on unexpected format

---

### Issue 5: Market Discovery Missing Series Endpoint

**Severity:** MEDIUM

**Impact:** Incomplete market discovery

**Location:** `client_public.py`, `market_catalog.py`

**Fix:** Add GET /series endpoint usage

---

### Issue 6: Order Routing Multiple Validation Layers

**Severity:** LOW

**Impact:** Unnecessary complexity

**Location:** `client.py` - `place_order_result()`

**Fix:** Consolidate validation into single function

---

### Issue 7: Ticker Resolution Dual Paths

**Severity:** MEDIUM

**Impact:** Inconsistent ticker resolution

**Location:** `market_selector.py`, `trading.py`

**Fix:** Use series-based resolution as single path

---

## Required Fixes

### Fix 1: Implement Single Orderbook Adapter

**Create:** `merid/event_venues/kalshi/types.py` - `NormalizedBook`

```python
@dataclass(frozen=True)
class NormalizedBook:
    """Canonical normalized orderbook from Kalshi API."""
    
    @classmethod
    def from_rest_response(cls, data: Dict[str, Any], ticker: str) -> "NormalizedBook":
        """Parse from GET /markets/{ticker}/orderbook raw response."""
        # Handle both documented and actual format
        orderbook = data.get("orderbook") or data.get("orderbook_fp", {})
        
        yes_levels = []
        if "yes" in orderbook:
            yes_levels = [[float(p), float(s)] for p, s in orderbook["yes"]]
        elif "yes_dollars" in orderbook:
            yes_levels = [[float(p), float(s)] for p, s in orderbook["yes_dollars"]]
        
        no_levels = []
        if "no" in orderbook:
            no_levels = [[float(p), float(s)] for p, s in orderbook["no"]]
        elif "no_dollars" in orderbook:
            no_levels = [[float(p), float(s)] for p, s in orderbook["no_dollars"]]
        
        return cls(ticker=ticker, yes_levels=yes_levels, no_levels=no_levels, source="REST")
    
    @classmethod
    def from_venue_orderbook(cls, orderbook: VenueOrderBook, ticker: str) -> "NormalizedBook":
        """Parse from VenueOrderBook object."""
        # Parse bids/asks
        return cls(ticker=ticker, yes_levels=yes_levels, no_levels=no_levels, source="REST")
    
    def to_snapshot_message(self) -> Dict[str, Any]:
        """Convert to WS snapshot message format."""
        return {
            "ticker": self.ticker,
            "type": "orderbook_snapshot",
            "yes": self.yes_levels,
            "no": self.no_levels,
        }
```

**Implementation:**
1. Add NormalizedBook adapter
2. Replace both parsing paths
3. Use in ws_bridge bootstrap
4. Use in REST fallback

---

### Fix 2: Remove HTTP Poller

**File:** `fills_poller.py`

**Action:** Deprecate and remove HTTP poller

**Rationale:**
- WS fills channel is primary source
- REST sync on reconnection provides backup
- HTTP poller is redundant

**Implementation:**
1. Mark as deprecated
2. Remove from initialization
3. Remove all references
4. Use WS + REST sync only

---

### Fix 3: Use Fills Ledger as Single Position Source

**File:** `client.py`, `kalshi_risk.py`

**Action:** Use fills_ledger.get_open_exposure_usd() for all position calculations

**Rationale:**
- Fills ledger is canonical source
- Filters out manually closed positions
- More accurate than REST positions

**Implementation:**
1. Replace REST positions with fills-derived positions
2. Use fills_ledger for all position calculations
3. Keep REST positions as validation only
4. Add reconciliation between REST and fills

---

### Fix 4: Remove Bankroll Dual Format Support

**File:** `client.py` - `get_balance_result()`

**Action:** Remove nested format handling

**Rationale:**
- Kalshi documents flat format only
- Nested format is defensive workaround
- Should fail on unexpected format

**Implementation:**
1. Remove nested format handling
2. Add validation for flat format
3. Fail on unexpected format
4. Remove silent negative correction

---

### Fix 5: Add Series Discovery Endpoint

**File:** `client_public.py`, `market_catalog.py`

**Action:** Add GET /series endpoint usage

**Rationale:**
- Kalshi has series endpoint
- Current implementation doesn't use it
- Series discovery is incomplete

**Implementation:**
1. Add list_series() method
2. Use in market catalog
3. Add startup guard for series discovery
4. Document series hierarchy

---

### Fix 6: Consolidate Order Validation

**File:** `client.py` - `place_order_result()`

**Action:** Create single validation function

**Rationale:**
- Multiple validation layers create complexity
- Guard + pre-send validation is redundant
- Single function is easier to maintain

**Implementation:**
1. Create _validate_order() function
2. Consolidate all validation logic
3. Call once before building payload
4. Remove scattered validation

---

### Fix 7: Use Series-Based Ticker Resolution

**File:** `market_selector.py`, `trading.py`

**Action:** Use series-based resolution as single path

**Rationale:**
- Series-based is preferred (documented)
- Category-based is fallback
- Dual paths create inconsistency

**Implementation:**
1. Remove category-based resolution
2. Use series-based for all agents
3. Add series_tickers to all agent configs
4. Document resolution path

---

## Audit Checklist

- [ ] Document orderbook data flow (✅ documented)
- [ ] Document fills data flow (✅ documented)
- [ ] Document positions data flow (✅ documented)
- [ ] Document bankroll data flow (✅ documented)
- [ ] Document market discovery data flow (✅ documented)
- [ ] Document order routing data flow (✅ documented)
- [ ] Document ticker resolution data flow (✅ documented)
- [ ] Identify orderbook dual parsing (🚨 high severity)
- [ ] Identify fills multiple paths (🚨 high severity)
- [ ] Identify positions dual sources (⚠️ medium severity)
- [ ] Identify bankroll dual format (⚠️ low severity)
- [ ] Identify missing series endpoint (⚠️ medium severity)
- [ ] Identify order validation layers (⚠️ low severity)
- [ ] Identify ticker resolution paths (⚠️ medium severity)
- [ ] Plan migration path (7 fixes)
- [ ] Implement single orderbook adapter
- [ ] Remove HTTP poller
- [ ] Use fills ledger as single position source
- [ ] Remove bankroll dual format support
- [ ] Add series discovery endpoint
- [ ] Consolidate order validation
- [ ] Use series-based ticker resolution

---

## Next Steps

1. **Immediate:** Implement single orderbook adapter
2. **Immediate:** Remove HTTP poller
3. **Short-term:** Use fills ledger as single position source
4. **Short-term:** Remove bankroll dual format support
5. **Medium-term:** Add series discovery endpoint
6. **Medium-term:** Consolidate order validation
7. **Medium-term:** Use series-based ticker resolution

**Priority:** HIGH - Multiple data flow paths create inconsistency risk

**Risk:** Dual parsing paths for orderbook and multiple ingestion paths for fills can lead to inconsistent data. Single source of truth for positions is unclear.

**Note:** Most data types have single pipelines, but orderbook, fills, and positions have multiple paths that need consolidation. Bankroll has a single pipeline but defensive workarounds.
