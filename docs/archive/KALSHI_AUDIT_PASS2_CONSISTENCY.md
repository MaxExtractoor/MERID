# Kalshi API Audit - Pass 2.2: Catalog→WS→Agent Consistency

**Objective:** For each series, confirm catalog knows all ticker values, WS subscribe uses those exact tickers, and agent grid uses those same tickers.

**Kalshi Reference:** 
- [docs.kalshi.com/quick_start_websockets](https://docs.kalshi.com/getting_started/quick_start_websockets)
- [quantvps.com/kalshi-order-book-api-endpoints](https://www.quantvps.com/blog/kalshi-order-book-api-endpoints-explained)

---

## Current State Analysis

### 1. Ticker Flow: Catalog → WS Bridge

#### Catalog Discovery

**File:** `market_catalog.py` - `get_markets_for_series()`

```python
async def get_markets_for_series(self, series_ticker: str) -> List[CatalogMarket]:
    """Query Kalshi REST API for markets belonging to a specific series."""
    _filter = MarketFilter(
        active_only=False,
        limit=200,
        search=series_ticker,
    )
    _result = await self._client.list_markets_result(_filter)
    
    # Convert to CatalogMarket objects
    _markets: List[CatalogMarket] = []
    for m in (_result.data or []):
        cm = self._enrich_market(m)
        _markets.append(cm)
    
    return _markets
```

**Ticker Source:** 
- Kalshi API `GET /markets?series_ticker=KXBTC15M`
- Stored in `CatalogMarket.market_id` (the ticker)

**Ticker Format:** Exact Kalshi ticker (e.g., `KXBTC15M-26MAY241830-30`)

**Status:** ✅ Uses exact API values

---

#### WS Bridge Subscription

**File:** `ws_bridge.py` - `start()`

```python
async def start(self, tickers: Optional[List[str]] = None) -> None:
    """Start WebSocket bridge and subscribe to tickers."""
    # Filter tickers
    filtered_tickers = []
    for ticker in ut:
        is_allowed = False
        for symbol in _ALLOWED_SYMBOLS:
            if symbol in ticker:
                if any(tf in ticker for tf in _ALLOWED_TIMEFRAMES):
                    is_allowed = True
                    break
        if is_allowed:
            filtered_tickers.append(ticker)
    
    # Subscribe
    self._subscribed_tickers = list(ut)
    for i in range(0, len(ut), ch):
        batch = ut[i : i + ch]
        await self._ws.subscribe_orderbooks_batch(batch)
```

**Ticker Source:** 
- Passed in as parameter `tickers` from caller
- Caller: `agent_grid_15m.py` - `start()`

**Ticker Format:** Exact Kalshi ticker (same as catalog)

**Status:** ✅ Uses exact catalog values

**Issues:**
- ⚠️ **Filtering logic:** Applies asset/timeframe filtering which could exclude valid tickers
- ⚠️ **No validation:** Doesn't verify tickers exist in catalog before subscribing

---

#### WS Bridge Subscription Implementation

**File:** `ws.py` - `subscribe_orderbooks_batch()`

```python
async def subscribe_orderbooks_batch(self, market_tickers: List[str]) -> None:
    """Subscribe to orderbook_delta channel for multiple markets."""
    for i in range(0, len(market_tickers), 50):
        batch = market_tickers[i : i + 50]
        payload = {
            "id": self._next_id(),
            "cmd": "subscribe",
            "params": {
                "channels": ["orderbook_delta"],
                "market_tickers": batch
            }
        }
        await self._send(payload)
```

**Payload Format:**
```json
{
  "id": 1,
  "cmd": "subscribe",
  "params": {
    "channels": ["orderbook_delta"],
    "market_tickers": ["KXBTC15M-26MAY241830-30", ...]
  }
}
```

**Status:** ✅ Matches Kalshi documented format

---

### 2. Ticker Flow: WS Bridge → Agent Grid

#### WS Bridge → MarketStateStore

**File:** `ws.py` - `_handle_message()`

```python
elif channel == "orderbook_delta":
    # Always forward deltas
    data["type"] = "orderbook_delta"
    return data
```

**Ticker Field:** `market_ticker` in WS message

**Status:** ✅ Preserves ticker from WS

---

#### MarketStateStore Storage

**File:** `market_state.py` - `apply_orderbook_message()`

```python
def apply_orderbook_message(self, msg: Dict[str, Any]) -> None:
    """Apply WS orderbook_snapshot or orderbook_delta message."""
    ticker = msg.get("ticker") or msg.get("market_ticker")
    
    with self._lock:
        state = self._states.get(ticker)
        # ... apply to state
```

**Ticker Key:** Uses `ticker` or `market_ticker` as state key

**Status:** ✅ Stores ticker as key

**Issues:**
- ⚠️ **Dual field support:** Accepts both `ticker` and `market_ticker` (inconsistent)

---

#### Agent Grid Usage

**File:** `agent_grid_15m.py` - `_generate_signal()`

```python
def _generate_signal(self, spot_price: float, market: Dict[str, Any], minutes_to_expiry: float):
    market_id = market.get("ticker", "")
    
    # Read bid/ask from KalshiMarketStateStore
    store = get_kalshi_market_state_store()
    state = store.get(market_id)
    
    logger.info(
        "[AGENT-STATE] series=%s market_id=%s book_initialized=%s ...",
        self.config.name,
        market_id,
        state.book_initialized
    )
```

**Ticker Source:** 
- `market` dict from catalog snapshot
- `market_id` field = `CatalogMarket.market_id`

**Status:** ✅ Uses catalog ticker

---

### 3. Ticker Flow: Catalog → Agent Grid

#### Catalog Snapshot

**File:** `agent_grid_15m.py` - `run_cycle()`

```python
async def run_cycle(self) -> None:
    """Run one trading cycle for all agents."""
    catalog_snapshot = self._catalog.snapshot()
    
    for agent in self._agents:
        markets = catalog_snapshot.markets
        for market in markets:
            # Generate signal
            signal = self._generate_signal(spot_price, market, minutes_to_expiry)
```

**Ticker Source:** 
- `catalog_snapshot.markets` - list of `CatalogMarket` objects
- Each has `market_id` field (the ticker)

**Status:** ✅ Uses catalog ticker

---

#### Agent Market Resolution

**File:** `market_selector.py` - `get_agent_market_tickers()`

```python
async def get_agent_market_tickers(
    agent_name: str,
    series_tickers: Optional[List[str]] = None
) -> List[str]:
    """Resolve agent to list of live market tickers."""
    series_list = series_tickers if series_tickers is not None else AGENT_SERIES_MAP.get(agent_name)
    
    for series_ticker in series_list:
        _series_markets = await catalog.get_markets_for_series(series_ticker)
        for mkt in _series_markets:
            market_id = mkt.market.market_id if hasattr(mkt, 'market') else mkt.market_id
            ticker_set.add(market_id)
    
    return sorted(ticker_set)
```

**Ticker Source:** 
- `catalog.get_markets_for_series(series_ticker)`
- `CatalogMarket.market_id`

**Status:** ✅ Uses catalog ticker

**Issues:**
- ⚠️ **Dual field access:** Checks both `mkt.market.market_id` and `mkt.market_id` (defensive but confusing)

---

### 4. Data Flow Diagram

```
Kalshi API (GET /markets?series_ticker=KXBTC15M)
    ↓
    market_id: "KXBTC15M-26MAY241830-30"
    ↓
market_catalog.py (CatalogMarket.market_id)
    ↓
agent_grid_15m.py (catalog_snapshot.markets)
    ↓
    market_id: "KXBTC15M-26MAY241830-30"
    ↓
ws_bridge.py (start(tickers=[...]))
    ↓
    market_tickers: ["KXBTC15M-26MAY241830-30", ...]
    ↓
Kalshi WS (subscribe orderbook_delta)
    ↓
    market_ticker: "KXBTC15M-26MAY241830-30"
    ↓
market_state.py (apply_orderbook_message)
    ↓
    ticker: "KXBTC15M-26MAY241830-30" (state key)
    ↓
agent_grid_15m.py (_generate_signal)
    ↓
    market_id: "KXBTC15M-26MAY241830-30"
```

**Status:** ✅ Ticker flows consistently through all layers

**Issues:**
- ⚠️ **Field name inconsistency:** Uses `market_id`, `ticker`, `market_ticker` interchangeably
- ⚠️ **No validation:** Doesn't verify ticker exists in catalog at each step
- ⚠️ **Filtering risk:** WS bridge filtering could exclude valid tickers

---

### 5. Consistency Check Implementation

#### Proposed Test Helper

```python
async def verify_ticker_consistency(series_ticker: str) -> Dict[str, Any]:
    """Verify ticker consistency across catalog, WS, and agent grid.
    
    For a given series, this checks:
    1. Catalog knows all tickers from Kalshi API
    2. WS subscribe uses those exact tickers
    3. Agent grid uses those same tickers
    
    Returns:
        Dict with consistency check results
    """
    from merid.event_venues.kalshi.market_catalog import get_kalshi_market_catalog
    from merid.event_venues.kalshi.market_state import get_kalshi_market_state_store
    
    catalog = get_kalshi_market_catalog()
    store = get_kalshi_market_state_store()
    
    # Step 1: Get tickers from catalog
    catalog_markets = await catalog.get_markets_for_series(series_ticker)
    catalog_tickers = {m.market_id for m in catalog_markets}
    
    # Step 2: Get tickers from WS bridge (subscribed)
    # (Need to expose _subscribed_tickers from ws_bridge)
    ws_tickers = set()  # TODO: Get from ws_bridge
    
    # Step 3: Get tickers from MarketStateStore
    state_tickers = set(store._states.keys())
    
    # Step 4: Check consistency
    results = {
        "series_ticker": series_ticker,
        "catalog_count": len(catalog_tickers),
        "ws_count": len(ws_tickers),
        "state_count": len(state_tickers),
        "catalog_tickers": sorted(catalog_tickers),
        "ws_tickers": sorted(ws_tickers),
        "state_tickers": sorted(state_tickers),
        "issues": []
    }
    
    # Check WS subset of catalog
    if not ws_tickers.issubset(catalog_tickers):
        missing = ws_tickers - catalog_tickers
        results["issues"].append(f"WS has tickers not in catalog: {missing}")
    
    # Check state subset of catalog
    if not state_tickers.issubset(catalog_tickers):
        missing = state_tickers - catalog_tickers
        results["issues"].append(f"State has tickers not in catalog: {missing}")
    
    # Check agent log consistency
    # (Would need to parse logs or add metrics)
    
    return results
```

**Implementation:**
1. Add to `merid/event_venues/kalshi/validation.py`
2. Call on startup for each priority series
3. Log warnings for inconsistencies
4. Fail startup if critical issues found

---

## Required Fixes

### Fix 1: Standardize Ticker Field Names

**Current:** Uses `market_id`, `ticker`, `market_ticker` interchangeably
**Target:** Use `market_ticker` everywhere (Kalshi documented field)

**Files to update:**
1. `market_catalog.py` - Keep `market_id` internally, expose `market_ticker`
2. `ws_bridge.py` - Use `market_ticker` consistently
3. `market_state.py` - Use `market_ticker` as state key
4. `agent_grid_15m.py` - Use `market_ticker` in logs

**Implementation:**
1. Add property to `CatalogMarket`: `@property def market_ticker(self) -> str: return self.market_id`
2. Update all references to use `market_ticker`
3. Document field name in docstrings

---

### Fix 2: Add Ticker Validation at Each Step

**File:** `ws_bridge.py` - `start()`

**Add validation:**
```python
async def start(self, tickers: Optional[List[str]] = None) -> None:
    """Start WebSocket bridge and subscribe to tickers."""
    # Validate tickers exist in catalog
    from merid.event_venues.kalshi.market_catalog import get_kalshi_market_catalog
    catalog = get_kalshi_market_catalog()
    catalog_snapshot = catalog.snapshot()
    catalog_tickers = {m.market_id for m in catalog_snapshot.markets}
    
    invalid_tickers = [t for t in tickers if t not in catalog_tickers]
    if invalid_tickers:
        logger.error(
            "[WS-BRIDGE] Tickers not in catalog: %s. Skipping subscription.",
            invalid_tickers
        )
        tickers = [t for t in tickers if t in catalog_tickers]
    
    # Subscribe with validated tickers
    # ... existing logic
```

**Implementation:**
1. Add validation before subscription
2. Log warnings for invalid tickers
3. Skip invalid tickers instead of failing

---

### Fix 3: Remove WS Bridge Filtering

**Current:** WS bridge applies asset/timeframe filtering
**Target:** Use exact catalog tickers without filtering

**File:** `ws_bridge.py` - `start()`

**Remove:**
```python
# Remove filtering logic
filtered_tickers = []
for ticker in ut:
    is_allowed = False
    for symbol in _ALLOWED_SYMBOLS:
        if symbol in ticker:
            if any(tf in ticker for tf in _ALLOWED_TIMEFRAMES):
                is_allowed = True
                break
    if is_allowed:
        filtered_tickers.append(ticker)

# Use unfiltered tickers
ut = tickers
```

**Implementation:**
1. Remove filtering logic
2. Use catalog tickers directly
3. Trust catalog to provide correct tickers

---

### Fix 4: Add Consistency Check on Startup

**File:** `agent_grid_15m.py` - `start()`

**Add check:**
```python
async def start(self) -> None:
    """Start the agent grid."""
    # ... existing startup logic
    
    # Verify ticker consistency
    await self._verify_ticker_consistency()

async def _verify_ticker_consistency(self) -> None:
    """Verify ticker consistency across catalog, WS, and state."""
    from config.kalshi_15m_crypto_config import KALSHI_15M_SERIES_TICKERS
    
    for asset, series_ticker in KALSHI_15M_SERIES_TICKERS.items():
        result = await verify_ticker_consistency(series_ticker)
        if result["issues"]:
            logger.error(
                "[AGENT-GRID] Ticker consistency issues for %s: %s",
                series_ticker,
                result["issues"]
            )
```

**Implementation:**
1. Add consistency check method
2. Call on startup
3. Log warnings for issues
4. Consider failing startup for critical issues

---

### Fix 5: Expose WS Bridge Subscribed Tickers

**File:** `ws_bridge.py`

**Add property:**
```python
@property
def subscribed_tickers(self) -> List[str]:
    """Return list of currently subscribed tickers."""
    return list(self._subscribed_tickers) if self._subscribed_tickers else []
```

**Implementation:**
1. Add property to expose subscribed tickers
2. Use in consistency check
3. Use in health monitoring

---

## Audit Checklist

- [ ] Document ticker flow from catalog to WS (✅ documented)
- [ ] Document ticker flow from WS to agent (✅ documented)
- [ ] Document ticker flow from catalog to agent (✅ documented)
- [ ] Identify field name inconsistencies (market_id/ticker/market_ticker)
- [ ] Identify filtering risk (WS bridge filtering)
- [ ] Identify missing validation (no catalog checks)
- [ ] Design consistency check helper (proposed)
- [ ] Plan migration path (5 fixes)
- [ ] Standardize ticker field names
- [ ] Add ticker validation at each step
- [ ] Remove WS bridge filtering
- [ ] Add consistency check on startup
- [ ] Expose WS bridge subscribed tickers

---

## Next Steps

1. **Immediate:** Implement consistency check helper
2. **Immediate:** Add consistency check to startup
3. **Short-term:** Standardize ticker field names
4. **Short-term:** Add ticker validation
5. **Medium-term:** Remove WS bridge filtering
6. **Medium-term:** Expose subscribed tickers
7. **Long-term:** Add automated consistency monitoring

**Priority:** HIGH - Inconsistent tickers can cause WS subscription failures or stale data

**Risk:** If catalog and WS tickers diverge, agents may operate on stale or missing market data.
