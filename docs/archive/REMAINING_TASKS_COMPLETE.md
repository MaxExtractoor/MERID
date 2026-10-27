# Remaining Integration Tasks - COMPLETE

## Summary
All 10 high-leverage tasks from the upstream/downstream analysis have been completed.

---

## P0 - Critical Tasks Completed

### ✅ Task 2: Wire fills_ledger to position_cache.on_fill()
**Files Modified**: `merid/event_venues/kalshi/position_cache.py`

**Changes**:
- Added `fill_id` parameter to `on_fill()` method signature
- Added `_fills_ledger` attribute to `KalshiPositionCache` class
- Implemented `_lookup_fill_source()` helper method that:
  - Queries fills_ledger for fill_source if fill_id provided
  - Falls back to client_order_id prefix detection (HEDGE_)
  - Returns "hedge" or "alpha"
- Updated fill detection logic to use authoritative ledger lookup

**Integration Pattern**:
```python
async def on_fill(self, ..., fill_id: Optional[str] = None):
    fill_source = await self._lookup_fill_source(fill_id, client_order_id)
    # Now position cache uses authoritative fill_source from ledger
```

---

### ✅ Task 4: Wire PnL tracker to ledger fill callbacks
**Files Modified**: `merid/event_venues/kalshi/fills_ledger.py`

**Changes**:
- Added `_pnl_tracker` attribute to `KalshiFillsLedger` class
- Added `set_pnl_tracker()` method for dependency injection
- Implemented `_notify_pnl_tracker_of_hedge_fill()` that:
  - Detects if fill is opening (new record) or closing (exit)
  - Creates PnL record for opening hedge fills
  - Records hedge exit for closing fills
- Wired notification into both `ingest_http_fills()` and `ingest_ws_fill()`

**Integration Pattern**:
```python
async def ingest_ws_fill(self, ...):
    # ... existing fill processing ...
    if fill.fill_source == "hedge":
        await self._notify_pnl_tracker_of_hedge_fill(fill)
```

---

### ✅ Task 7: Add auto-save trigger to persistence
**Files Modified**: `merid/event_venues/kalshi/fills_ledger.py`

**Changes**:
- Added `_persistence_manager` and `_last_auto_save` attributes
- Added `_auto_save_interval_minutes` (configurable via env var)
- Implemented `set_persistence_manager()` for dependency injection
- Implemented `_maybe_trigger_auto_save()` that:
  - Checks if interval has elapsed since last save
  - Gets hedge fills via optimized `get_hedge_fills()` query
  - Persists both fills and PnL tracker state
  - Handles errors gracefully with logging
- Wired auto-save into both HTTP and WebSocket fill ingestion

**Environment Variable**:
```bash
export MERID_HEDGE_AUTO_SAVE_MINUTES=5  # Default: 5 minutes
```

---

## P1 - High Priority Tasks Completed

### ✅ Task 9: Ensure hedge order flow with HEDGE_ prefix
**Files Modified**: `merid/hedging/engine.py`

**Changes**:
- Enhanced `_deterministic_tag()` with defensive HEDGE_ prefix enforcement
- Added explicit documentation about Task 9 requirements
- Double-checks that all generated tags start with HEDGE_ prefix

**Verification**:
```python
tag = f"{HEDGE_CLIENT_TAG_PREFIX}{purpose}_{timeframe}_{h}"
# Defensive check
if not tag.startswith(HEDGE_CLIENT_TAG_PREFIX):
    tag = f"{HEDGE_CLIENT_TAG_PREFIX}{tag}"
```

---

### ✅ Task 10: Hedge Order Intent Tags
**Files Modified**: `merid/hedging/engine.py`

**Status**: Already implemented in `to_order_intents()` method:
- `source="hedge"` - Identifies intent as hedge order
- `agent="hedge_engine"` - Tracks which component generated it
- `client_tag=ho.client_tag` - Includes HEDGE_ prefix for fill detection
- `metadata["hedge_reason"]` - Stores why hedge was created

**Output Format**:
```python
OrderIntent(
    intent_id=f"hedge_{ho.asset}_{ho.timeframe}_{uuid4().hex[:8]}",
    market_ticker=ho.target_ticker,
    side=ho.side,
    contracts=ho.count,
    limit_price_cents=ho.price_cents,
    source="hedge",  # Task 10: Hedge source tag
    agent="hedge_engine",
    client_tag=ho.client_tag,  # Contains HEDGE_ prefix
    metadata={
        "hedge_reason": ho.hedge_reason,
        "is_hedge": True,
    },
)
```

---

## Integration Architecture

### Complete Data Flow

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│  Hedge Engine   │────▶│   fills_ledger  │────▶│  PnL Tracker    │
│                 │     │                 │     │                 │
│ - Generates     │     │ - Auto-tags     │     │ - Creates       │
│   HEDGE_ tags   │     │   by prefix     │     │   records       │
│ - Creates       │     │ - Notifies PnL  │     │ - Tracks        │
│   OrderIntents  │     │   tracker       │     │   effectiveness │
└─────────────────┘     └─────────────────┘     └─────────────────┘
         │                       │
         ▼                       ▼
┌─────────────────┐     ┌─────────────────┐
│ Position Cache  │◀────│  Persistence    │
│                 │     │  Manager        │
│ - Queries       │     │                 │
│   fill_source   │     │ - Auto-saves    │
│   from ledger   │     │   every N min   │
└─────────────────┘     └─────────────────┘
```

### Setup Code

```python
# Initialize components with wiring
from merid.event_venues.kalshi.fills_ledger import get_fills_ledger
from merid.event_venues.kalshi.position_cache import get_position_cache
from merid.hedging.pnl_tracker import get_hedge_pnl_tracker
from merid.event_venues.kalshi.fills_persistence import HedgePersistenceManager

# Get singletons
ledger = get_fills_ledger()
cache = get_position_cache()
pnl_tracker = get_hedge_pnl_tracker()
persistence = HedgePersistenceManager()

# Wire integrations (Task 2, 4, 7)
ledger.set_pnl_tracker(pnl_tracker)
ledger.set_persistence_manager(persistence)
# Note: position_cache._fills_ledger is set internally
```

---

## Environment Variables Summary

| Variable | Default | Purpose |
|----------|---------|---------|
| `MERID_HEDGE_CRYPTO_ASSETS` | `BTC,ETH,SOL` | Assets to hedge |
| `HEDGE_NEUTRAL_THRESHOLD_CENTS` | `1000` | Neutral classification threshold |
| `MAX_HEDGE_COVERAGE_RATIO` | `2.0` | Max hedge coverage cap |
| `MERID_HEDGE_DATA_DIR` | `~/.merid/hedge_data` | Persistence directory |
| `MERID_HEDGE_AUTO_SAVE_MINUTES` | `5` | Auto-save interval |

---

## All 10 Tasks Status

| Task | Description | Status | Files |
|------|-------------|--------|-------|
| 1 | Position Cache Hedge Fill Recognition | ✅ Complete | `position_cache.py` |
| 2 | Wire fills_ledger to position_cache | ✅ Complete | `position_cache.py` |
| 3 | Asset Map Dynamic Extraction | ✅ Complete | `dashboard_queries.py` |
| 4 | Wire PnL tracker to ledger | ✅ Complete | `fills_ledger.py` |
| 5 | Configurable Neutral Threshold | ✅ Complete | `exposure.py` |
| 6 | Configurable Coverage Cap | ✅ Complete | `exposure.py`, `dashboard_queries.py` |
| 7 | Auto-save triggers | ✅ Complete | `fills_ledger.py` |
| 8 | Configurable Persistence Path | ✅ Complete | `fills_persistence.py` |
| 9 | HEDGE_ prefix enforcement | ✅ Complete | `engine.py` |
| 10 | Hedge Intent Tags | ✅ Complete | `engine.py` |

---

## Production Verification

```python
# Test hedge order generation
from merid.hedging.engine import CryptoHedgeEngine
engine = CryptoHedgeEngine()
orders = engine.compute_hedge_orders(...)
for o in orders:
    assert o.client_tag.startswith("HEDGE_"), "Task 9: HEDGE_ prefix missing"
    intents = engine.to_order_intents([o])
    assert intents[0].source == "hedge", "Task 10: source tag missing"
    assert intents[0].metadata.get("hedge_reason"), "Task 10: hedge_reason missing"

# Test fill detection
from merid.event_venues.kalshi.fills_ledger import get_fills_ledger
ledger = get_fills_ledger()
ledger.set_pnl_tracker(pnl_tracker)
ledger.set_persistence_manager(persistence)
# Ingest hedge fill → Should trigger PnL record creation

# Test position cache lookup
from merid.event_venues.kalshi.position_cache import get_position_cache
cache = get_position_cache()
# on_fill with fill_id should query ledger for fill_source
```
