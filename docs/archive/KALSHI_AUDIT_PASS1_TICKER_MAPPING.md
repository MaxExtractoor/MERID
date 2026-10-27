# Kalshi API Audit - Pass 1.1: Ticker and Series Mapping

**Objective:** Every concept in your codebase (series, ticker, book, order, position) maps 1:1 to a specific Kalshi field or endpoint, with no home-rolled assumptions.

**Kalshi Reference:** [docs.kalshi.com/terms](https://docs.kalshi.com/getting_started/terms)

---

## Current State Analysis

### 1. Series Ticker Construction Locations

#### Location 1: `market_selector.py` - `resolve_series_ticker()`
```python
def resolve_series_ticker(coin: str, timeframe: str) -> str:
    base = CRYPTO_SERIES_BASE.get(coin.upper())  # e.g., "KXBTC"
    suffix = TIMEFRAME_SERIES_SUFFIX.get(timeframe.lower(), "")  # e.g., "15M"
    ticker = f"{base}{suffix}"  # e.g., "KXBTC15M"
```

**Purpose:** Construct series tickers from coin + timeframe for agent configuration

**Kalshi Field Mapping:**
- **Intended to map to:** `series_ticker` from `GET /series` or `GET /markets`
- **Current status:** ✅ Correct format matches Kalshi documented series tickers
- **Verified against:** kalshi.com/category/crypto/frequency/fifteen_min

**Examples:**
- `resolve_series_ticker("BTC", "15m")` → `"KXBTC15M"` ✅
- `resolve_series_ticker("ETH", "15m")` → `"KXETH15M"` ✅
- `resolve_series_ticker("SOL", "15m")` → `"KXSOL15M"` ✅
- `resolve_series_ticker("XRP", "15m")` → `"KXXRP15M"` ✅
- `resolve_series_ticker("DOGE", "15m")` → `"KXDOGE15M"` ✅

**Issues:**
- ⚠️ **String construction** instead of using Kalshi API values directly
- ⚠️ **Hardcoded whitelist** in function (only allows 5 specific series)

---

#### Location 2: `market_catalog.py` - Series Ticker Extraction and Override
```python
# Extract series_ticker from raw API response
series_ticker = raw.get("series_ticker", "") or ""

# CRITICAL FIX: Override series_ticker from market_id if API returns incorrect value
# Kalshi API returns KXBTC instead of KXBTC15M for series_ticker field
series_match = re.match(r"^(KX[A-Z]+15M|KX[A-Z]+H1|KX[A-Z]+D1|KX[A-Z]+W1|KX[A-Z]+1M|KX[A-Z]+Y|KX[A-Z]+)", mkt.market_id.upper())
if series_match:
    extracted_series = series_match.group(1)
    if series_ticker != extracted_series:
        series_ticker = extracted_series
        mkt.raw_data["series_ticker"] = extracted_series
```

**Purpose:** Extract series_ticker from Kalshi API response, with fallback to market_id parsing

**Kalshi Field Mapping:**
- **Reads from:** `series_ticker` field in `GET /markets` response
- **Fallback to:** `market_id` field (parsed with regex)
- **Current status:** ⚠️ **Workaround for API bug** - Kalshi API returns incorrect series_ticker

**Issues:**
- 🚨 **API inconsistency:** Kalshi returns `KXBTC` instead of `KXBTC15M` in series_ticker field
- 🚨 **Regex parsing:** Fallback to parsing market_id is fragile and not documented by Kalshi
- 🚨 **Data mutation:** Modifies raw_data to override API response

**Root Cause:** Kalshi API bug where series_ticker field doesn't match documented format

**Required Fix:** 
1. Report bug to Kalshi
2. Remove regex fallback once API is fixed
3. Use only API-provided series_ticker field

---

#### Location 3: `market_state.py` - Series Ticker Reconstruction
```python
# Extract series ticker from market ticker
asset = kalshi_ticker_to_asset(ticker) or "UNKNOWN"
timeframe = get_series_timeframe_bucket(ticker) or "UNKNOWN"
series_ticker = f"{asset.upper()}{timeframe.upper()}" if asset != "UNKNOWN" else "UNKNOWN"
```

**Purpose:** Reconstruct series_ticker from market ticker for health logging

**Kalshi Field Mapping:**
- **Intended to map to:** `series_ticker` from `GET /markets`
- **Current status:** ⚠️ **Reconstruction from ticker** instead of using stored value
- **Source:** `kalshi_ticker_to_asset()` and `get_series_timeframe_bucket()` functions

**Issues:**
- ⚠️ **String construction** instead of using catalog-provided series_ticker
- ⚠️ **Dependency on parsing functions** that may not match Kalshi format exactly
- ⚠️ **No validation** that reconstructed series_ticker matches catalog

**Required Fix:**
- Pass series_ticker from catalog instead of reconstructing
- Remove reconstruction logic entirely

---

#### Location 4: `order_router.py` - Hardcoded Series Ticker Mappings
```python
series_ticker = None
if parts and len(parts) >= 2:
    series_ticker = parts[0]  # Extract from ticker
else:
    # Fallback to hardcoded mappings
    if asset == "BTC":
        series_ticker = "KXBTC15M"
    elif asset == "ETH":
        series_ticker = "KXETH15M"
    elif asset == "SOL":
        series_ticker = "KXSOL15M"
    elif asset == "XRP":
        series_ticker = "KXXRP15M"
    elif asset == "DOGE":
        series_ticker = "KXDOGE15M"
```

**Purpose:** Determine series_ticker for order validation

**Kalshi Field Mapping:**
- **Intended to map to:** `series_ticker` from `GET /markets`
- **Current status:** ⚠️ **Hardcoded fallback** for 5 specific assets
- **Primary path:** Extract from ticker parts

**Issues:**
- ⚠️ **Hardcoded values** duplicate logic from market_selector.py
- ⚠️ **No validation** that hardcoded values match current Kalshi series
- ⚠️ **Maintenance burden:** Must update if Kalshi adds new series

**Required Fix:**
- Remove hardcoded fallback
- Use catalog-provided series_ticker for all orders
- Fail-fast if series_ticker cannot be determined

---

### 2. Market Ticker (ticker) Usage

#### Kalshi Definition
From [docs.kalshi.com/terms](https://docs.kalshi.com/getting_started/terms):
- **ticker:** Unique identifier for a specific market (e.g., `KXBTC15M-26MAY241830-30`)
- **series_ticker:** Identifier for a series of markets (e.g., `KXBTC15M`)
- **event_ticker:** Identifier for an event (e.g., `KXBTC-26MAY241830`)

#### Current Usage in Codebase

**Catalog (market_catalog.py):**
- ✅ Uses `market_id` from API as the primary ticker
- ✅ Stores in `CatalogMarket.market_id` field
- ✅ Passes to agents via catalog snapshot

**WS Bridge (ws_bridge.py):**
- ✅ Subscribes using exact market_id values from catalog
- ✅ Receives orderbook_delta messages with ticker field
- ✅ Uses ticker as key in MarketStateStore

**Agent Grid (agent_grid_15m.py):**
- ✅ Uses market_id from catalog for signal generation
- ✅ Logs ticker in [AGENT-STATE] messages
- ✅ Passes ticker to order_router

**Issues:**
- ⚠️ **No validation** that ticker format matches Kalshi spec
- ⚠️ **No central type** for ticker (string used everywhere)

---

### 3. Data Flow Diagram

```
Kalshi API (GET /markets)
    ↓
    series_ticker (API field, may be incorrect)
    market_id (API field, correct)
    event_ticker (API field)
    ↓
market_catalog.py
    ↓
    Extract series_ticker from market_id (regex workaround)
    Override raw_data["series_ticker"]
    ↓
    CatalogMarket.market_id (used as ticker)
    CatalogMarket.series_ticker (overridden value)
    ↓
agent_grid_15m.py
    ↓
    Use market_id as ticker for signals
    ↓
order_router.py
    ↓
    Reconstruct series_ticker from ticker (hardcoded fallback)
    ↓
Kalshi API (POST /portfolio/orders)
```

**Issues in Flow:**
1. 🚨 **Series_ticker extracted from market_id** instead of using API field
2. 🚨 **Series_ticker reconstructed in order_router** instead of using catalog value
3. 🚨 **Multiple construction points** create inconsistency risk
4. 🚨 **No single source of truth** for series_ticker

---

## Required Fixes

### Fix 1: Introduce KalshiIds Dataclass

```python
@dataclass(frozen=True)
class KalshiIds:
    """Canonical Kalshi identifiers - single source of truth.
    
    All fields come directly from Kalshi API responses.
    No construction or parsing in application code.
    """
    series_ticker: str  # From GET /markets series_ticker field
    ticker: str        # From GET /markets ticker field (market_id)
    event_ticker: str  # From GET /markets event_ticker field
    category: str      # From GET /markets category field
    tags: List[str]    # From GET /markets tags field
```

**Implementation:**
1. Add to `merid/event_venues/kalshi/types.py`
2. Populate in `market_catalog.py` from API response
3. Pass through pipeline instead of raw strings
4. Remove all ticker construction logic

---

### Fix 2: Remove Series Ticker Construction

**Files to modify:**
1. `market_selector.py` - Keep only for config validation, not runtime construction
2. `market_state.py` - Remove reconstruction, use catalog value
3. `order_router.py` - Remove hardcoded fallback, use catalog value
4. `market_catalog.py` - Remove regex workaround once API is fixed

**Migration path:**
1. Phase 1: Add KalshiIds to catalog, pass to all consumers
2. Phase 2: Update consumers to use KalshiIds fields
3. Phase 3: Remove construction logic
4. Phase 4: Report Kalshi API bug, remove workaround when fixed

---

### Fix 3: Add Ticker Format Validation

```python
def validate_kalshi_ticker(ticker: str) -> bool:
    """Validate ticker matches Kalshi documented format.
    
    Format: KX{ASSET}{TIMEFRAME}-{DATE}{TIME}-{STRIKE}
    Example: KXBTC15M-26MAY241830-30
    
    Reference: https://docs.kalshi.com/getting_started/terms
    """
    pattern = r"^KX[A-Z]+[0-9A-Z]+-[0-9A-Z]+-[0-9]+$"
    return bool(re.match(pattern, ticker.upper()))
```

**Implementation:**
1. Add to `merid/event_venues/kalshi/validation.py`
2. Call in catalog when parsing API response
3. Call in order_router before submitting orders
4. Fail-fast on invalid format

---

### Fix 4: Centralize Ticker Usage

**Current state:** Ticker passed as string everywhere
**Target state:** Ticker always accessed via KalshiIds.ticker

**Benefits:**
- Single source of truth
- Type safety
- Documentation via field names
- Easier to audit

---

## Audit Checklist

- [ ] Document all ticker construction locations (5 found)
- [ ] Map each construction to Kalshi field (documented above)
- [ ] Identify API inconsistencies (series_ticker bug)
- [ ] Design KalshiIds dataclass (proposed)
- [ ] Plan migration path (4 phases)
- [ ] Add ticker format validation (proposed)
- [ ] Remove hardcoded fallbacks (order_router.py)
- [ ] Remove regex workaround (market_catalog.py)
- [ ] Remove reconstruction logic (market_state.py)
- [ ] Report Kalshi API bug

---

## Next Steps

1. **Immediate:** Implement KalshiIds dataclass
2. **Short-term:** Add to catalog, update agent grid
3. **Medium-term:** Migrate all consumers to use KalshiIds
4. **Long-term:** Remove construction logic, report API bug

**Priority:** HIGH - Multiple construction points create inconsistency risk
