# Kalshi API Audit - Pass 2.1: Series/Market Discovery

**Objective:** Verify catalog layer is a faithful mirror of Kalshi's discovery model.

**Kalshi Reference:** 
- [docs.kalshi.com/quick_start_market_data](https://docs.kalshi.com/getting_started/quick_start_market_data)
- [docs.kalshi.com/terms](https://docs.kalshi.com/getting_started/terms)

---

## Current State Analysis

### 1. Series Discovery

#### Kalshi Documented Endpoints

**GET /series** (Series List)
- Purpose: List all available series
- Parameters: `category`, `tags`
- Response: Array of series with `series_ticker`, `title`, `category`

**GET /series/{series_ticker}** (Series Details)
- Purpose: Get details for a specific series
- Response: Series metadata, market count

---

#### Current Implementation

**Finding:** Code does NOT use `GET /series` endpoint

**Files examined:**
- `client.py` - No series endpoint calls
- `client_public.py` - No series endpoint calls
- `market_catalog.py` - No series endpoint calls

**Impact:**
- ⚠️ **Missing series validation:** No way to verify series_ticker exists before querying markets
- ⚠️ **Hardcoded series list:** Relies on hardcoded `KALSHI_15M_SERIES_TICKERS` in config
- ⚠️ **No series metadata:** Cannot access series title, category, etc.

**Status:** ⚠️ Series discovery not implemented

**Required Fix:**
1. Add `GET /series` endpoint to client
2. Validate series_ticker against API before market discovery
3. Cache series metadata for reference
4. Use API as source of truth for series list

---

### 2. Market Discovery

#### Kalshi Documented Endpoint

**GET /markets** (Market List)
- Purpose: List markets with filters
- Parameters:
  - `series_ticker` - Filter by series
  - `status` - Filter by status (open, closed, all)
  - `limit` - Max results per page
  - `cursor` - Pagination cursor
- Response: Array of markets with full metadata

---

#### Current Implementation: `client_public.py` - `list_open_markets_for_series()`

```python
async def list_open_markets_for_series(
    self,
    series_ticker: str,
    min_close_ts: Optional[int] = None,
    max_close_ts: Optional[int] = None,
    limit: int = 1000,
) -> List[PublicMarketInfo]:
    """Public market discovery for a single series with cursor-based pagination."""
    cursor = None
    all_markets: List[dict] = []
    
    while True:
        params = {"series_ticker": series_ticker, "status": "open"}
        if cursor:
            params["cursor"] = cursor
        if limit:
            params["limit"] = str(limit)
        if min_close_ts is not None:
            params["min_close_ts"] = str(min_close_ts)
        if max_close_ts is not None:
            params["max_close_ts"] = str(max_close_ts)

        http = self._get_http()
        r = await http.get("/markets", params=params)
        r.raise_for_status()
        
        data = r.json()
        markets = data.get("markets", [])
        all_markets.extend(markets)
        
        # Pagination logic
        cursor = data.get("cursor")
        if not cursor:
            break
```

**Endpoint Used:** `GET /markets`

**Parameters:**
- ✅ `series_ticker` - Correctly used
- ✅ `status` - Set to "open" (hardcoded)
- ✅ `limit` - Configurable
- ✅ `cursor` - Pagination implemented
- ⚠️ `min_close_ts` - Custom parameter (not in Kalshi docs)
- ⚠️ `max_close_ts` - Custom parameter (not in Kalshi docs)

**Issues:**
- ⚠️ **Custom parameters:** `min_close_ts` and `max_close_ts` not documented in Kalshi API
- ⚠️ **Hardcoded status:** Always uses "open", cannot query closed markets
- ⚠️ **No status=all option:** Cannot validate plumbing in dev mode as audit suggests

**Status:** ⚠️ Mostly correct, but missing documented flexibility

**Required Fix:**
1. Verify if `min_close_ts`/`max_close_ts` are undocumented Kalshi features or custom
2. Add `status` parameter to allow "all" for dev validation
3. Document which parameters are Kalshi-supported vs custom

---

#### Current Implementation: `client.py` - `list_markets_result()`

```python
async def list_markets_result(
    self,
    filter_params: Optional[MarketFilter] = None
) -> OperationResult[List[EventMarket]]:
    """List Kalshi markets (public discovery path, hardened)."""
    filter_params = filter_params or MarketFilter()
    
    # Discovery only supports `search` as series_ticker + active_only (status=open).
    if not filter_params.search:
        return OperationResult.fail(
            "list_markets_result requires search=series_ticker for public discovery"
        )
    
    series_ticker = filter_params.search
    
    # Freshness cutoff
    min_close_ts = None
    if _settings.KALSHI_MIN_CLOSE_SECONDS_AGO is not None:
        cutoff = now - timedelta(seconds=_settings.KALSHI_MIN_CLOSE_SECONDS_AGO)
        min_close_ts = int(cutoff.timestamp())
    
    public_markets = await self._public.list_open_markets_for_series(
        series_ticker=series_ticker,
        min_close_ts=min_close_ts,
    )
```

**Issues:**
- 🚨 **Parameter mapping:** Maps `filter_params.search` to `series_ticker` (confusing naming)
- 🚨 **Custom freshness logic:** Implements custom time-based filtering not in Kalshi API
- 🚨 **No status parameter:** Cannot query closed markets
- 🚨 **Hard requirement:** Requires `search` parameter, no unfiltered discovery

**Status:** 🚨 Over-engineered with custom logic

**Required Fix:**
1. Rename `search` to `series_ticker` for clarity
2. Remove custom freshness logic (use Kalshi's close time filtering if available)
3. Add `status` parameter to MarketFilter
4. Allow unfiltered discovery for dev validation

---

### 3. Catalog Refresh

#### Current Implementation: `market_catalog.py` - `_refresh_loop()`

```python
async def _refresh_loop(self) -> None:
    """Periodically refresh catalog from Kalshi API."""
    while self._running:
        try:
            # Fetch markets for priority series
            for series_ticker in self._PRIORITY_SERIES:
                markets = await self.get_markets_for_series(series_ticker)
                # Update catalog
        except Exception as e:
            logger.error(f"Catalog refresh failed: {e}")
        
        await asyncio.sleep(self._refresh_interval)
```

**Priority Series:**
```python
_PRIORITY_SERIES = [
    "KXBTC15M", "KXETH15M", "KXSOL15M", "KXXRP15M", "KXDOGE15M",
    "KXBTC", "KXETH", "KXSOL", "KXXRP", "KXDOGE",
    # ... more series
]
```

**Issues:**
- ⚠️ **Hardcoded series list:** Relies on hardcoded `_PRIORITY_SERIES`
- ⚠️ **No series validation:** Doesn't verify series exist via `GET /series`
- ⚠️ **No startup guard:** If API returns 0 markets, continues anyway
- ⚠️ **Sequential refresh:** Refreshes series one at a time (slow)

**Status:** ⚠️ Missing validation and startup guard

**Required Fix:**
1. Add startup guard: abort if total_markets == 0 for 15m series
2. Validate series existence via `GET /series` before querying markets
3. Add parallel refresh for multiple series
4. Log warnings for series with 0 markets

---

### 4. Data Flow Diagram

```
Config (KALSHI_15M_SERIES_TICKERS)
    ↓
    Hardcoded series list
    ↓
market_catalog.py (_refresh_loop)
    ↓
    get_markets_for_series(series_ticker)
    ↓
client.py (list_markets_result)
    ↓
    client_public.py (list_open_markets_for_series)
    ↓
    GET /markets?series_ticker=KXBTC15M&status=open
    ↓
    Kalshi API
    ↓
    Market list
    ↓
    CatalogMarket objects
    ↓
    Agent grid
```

**Issues in Flow:**
1. 🚨 **No series validation:** Hardcoded list not verified against API
2. 🚨 **No startup guard:** Continues even if API returns 0 markets
3. 🚨 **Custom filtering:** Freshness logic not in Kalshi API
4. 🚨 **Sequential refresh:** Slow performance

---

## Required Fixes

### Fix 1: Add Series Discovery

**File:** `client_public.py`

**Add method:**
```python
async def list_series(
    self,
    category: Optional[str] = None,
    tags: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """List all available series from Kalshi API.
    
    Args:
        category: Filter by category (e.g., "crypto")
        tags: Filter by tags
    
    Returns:
        List of series with series_ticker, title, category
    """
    params = {}
    if category:
        params["category"] = category
    if tags:
        params["tags"] = ",".join(tags)
    
    http = self._get_http()
    r = await http.get("/series", params=params)
    r.raise_for_status()
    
    data = r.json()
    return data.get("series", [])
```

**Implementation:**
1. Add to `client_public.py`
2. Call on startup to validate series list
3. Cache series metadata
4. Use as source of truth for series list

---

### Fix 2: Add Startup Guard

**File:** `market_catalog.py` - `_refresh_loop()`

**Add guard:**
```python
async def _refresh_loop(self) -> None:
    """Periodically refresh catalog from Kalshi API."""
    # Initial refresh with startup guard
    await self._initial_refresh()
    
    while self._running:
        # ... existing refresh logic

async def _initial_refresh(self) -> None:
    """Initial catalog refresh with startup guard."""
    total_markets = 0
    for series_ticker in self._PRIORITY_SERIES:
        markets = await self.get_markets_for_series(series_ticker)
        total_markets += len(markets)
    
    # Startup guard: abort if no markets for 15m series
    if total_markets == 0:
        logger.error(
            "[CATALOG-STARTUP-GUARD] No markets discovered for priority series. "
            "Aborting startup to prevent running on synthetic data."
        )
        raise RuntimeError("Catalog discovery failed: no markets found")
    
    logger.info(
        "[CATALOG-STARTUP-GUARD] Discovered %d markets for priority series",
        total_markets
    )
```

**Implementation:**
1. Add `_initial_refresh()` method
2. Add guard after initial refresh
3. Raise error if no markets found
4. Log warning for series with 0 markets

---

### Fix 3: Add Status Parameter

**File:** `client_public.py` - `list_open_markets_for_series()`

**Add parameter:**
```python
async def list_open_markets_for_series(
    self,
    series_ticker: str,
    status: str = "open",  # "open", "closed", "all"
    min_close_ts: Optional[int] = None,
    max_close_ts: Optional[int] = None,
    limit: int = 1000,
) -> List[PublicMarketInfo]:
    """Public market discovery for a single series."""
    params = {"series_ticker": series_ticker, "status": status}
    # ... rest of implementation
```

**Implementation:**
1. Add `status` parameter
2. Default to "open" for production
3. Use "all" for dev validation
4. Document in docstring

---

### Fix 4: Remove Custom Freshness Logic

**File:** `client.py` - `list_markets_result()`

**Remove:**
```python
# Remove custom freshness cutoff
min_close_ts = None
if _settings.KALSHI_MIN_CLOSE_SECONDS_AGO is not None:
    cutoff = now - timedelta(seconds=_settings.KALSHI_MIN_CLOSE_SECONDS_AGO)
    min_close_ts = int(cutoff.timestamp())
```

**Replace with:**
```python
# Use Kalshi's close time filtering if available
# (verify if min_close_ts is supported by API)
```

**Implementation:**
1. Remove custom freshness logic
2. Verify if Kalshi supports close time filtering
3. If yes, use API parameter
4. If no, implement in application layer with clear documentation

---

### Fix 5: Validate Series on Startup

**File:** `market_catalog.py` - `start()`

**Add validation:**
```python
async def start(self) -> None:
    """Start catalog refresh loop."""
    # Validate series against Kalshi API
    await self._validate_series()
    
    # Start refresh loop
    self._running = True
    self._task = asyncio.create_task(self._refresh_loop())

async def _validate_series(self) -> None:
    """Validate priority series exist in Kalshi API."""
    series_list = await self._client._public.list_series(category="crypto")
    api_series = {s.get("series_ticker") for s in series_list}
    
    for series_ticker in self._PRIORITY_SERIES:
        if series_ticker not in api_series:
            logger.warning(
                "[CATALOG-VALIDATION] Series %s not found in Kalshi API. "
                "This series may not exist or may be deprecated.",
                series_ticker
            )
```

**Implementation:**
1. Add `_validate_series()` method
2. Call on startup
3. Log warnings for missing series
4. Consider removing missing series from priority list

---

## Audit Checklist

- [ ] Document series discovery (not implemented)
- [ ] Document market discovery (GET /markets)
- [ ] Identify missing series endpoint (not used)
- [ ] Identify custom parameters (min_close_ts, max_close_ts)
- [ ] Identify hardcoded status (always "open")
- [ ] Identify missing startup guard (no validation)
- [ ] Design series discovery method (proposed)
- [ ] Design startup guard (proposed)
- [ ] Plan migration path (5 fixes)
- [ ] Add status parameter (open/closed/all)
- [ ] Remove custom freshness logic
- [ ] Add series validation on startup
- [ ] Test with status=all for dev validation

---

## Next Steps

1. **Immediate:** Verify if min_close_ts/max_close_ts are Kalshi-supported or custom
2. **Immediate:** Add series discovery endpoint to client
3. **Short-term:** Implement startup guard
4. **Short-term:** Add status parameter
5. **Medium-term:** Remove custom freshness logic
6. **Medium-term:** Add series validation
7. **Long-term:** Use API as source of truth for series list

**Priority:** HIGH - Missing startup guard can cause trading on synthetic data

**Risk:** If API returns 0 markets, system may continue with empty catalog and fail silently.
