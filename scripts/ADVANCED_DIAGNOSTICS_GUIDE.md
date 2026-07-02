# Advanced Diagnostics Guide

This document describes the advanced diagnostic probes created to test time and state coherence with the live server, and provides a framework for prioritizing fixes based on probe results.

## Overview

The previous diagnostic scripts proved that components *exist*. These new probes prove they are **coherent in time and state** with the live server by connecting to the running server's singletons.

## Diagnostic Scripts Created

### 1. Time Alignment and Active Window Probe
**File:** `merid/diagnostics/time_alignment.py`

**Purpose:** Prove whether the process notion of "now" and Kalshi's market times are aligned, and quantify any skew + mis-selection.

**What it checks:**
- Server "now" (`datetime.now(timezone.utc)`) from inside the live process
- For each series, pulls full list of markets
- For each market, computes `open_time_utc` and `close_time_utc` solely from `close_ts` (no ticker parsing)
- Tags each market as `LIVE` (`open <= now < close`), `RECENT` (`0 < now - close <= 5m`), `FUTURE`, `OLD`
- Compares catalog's "active" market vs pure `close_ts` filter's "live" market

**Why it helps:**
- Shows if catalog logic is picking IDs whose `close_ts` is actually OLD or FUTURE
- Shows time skew between `now_utc` and Kalshi's `close_time` pattern
- Quantifies how many series are wrong at once

**HTTP Endpoint:** `/diagnostics/time_alignment`

---

### 2. Catalog vs WS Subscriptions vs MD State Probe
**File:** `merid/diagnostics/catalog_ws_md_consistency.py`

**Purpose:** Verify that catalog active markets, WS subscriptions, and market-state orderbooks are all tracking the same set of tickers.

**What it checks:**
- For each series:
  - Catalog: `active_markets` using fixed UTC/close_ts logic
  - WS layer: current subscribed market IDs
  - Market-state: `KalshiMarketStateStore` entries with last update time, `yes_bid/yes_ask`, `book_init`
- Computes differences between each layer
- Flags mismatches or stale MD age > 60s as hard errors

**Why it helps:**
- Exposes exact tickers where you "find everything except the active one"
- Tells whether problem is catalog picking wrong IDs, WS subscribing wrongly, or MD not applying updates

**HTTP Endpoint:** `/diagnostics/catalog_ws_md_consistency`

---

### 3. WebSocket Raw Traffic vs Parsed MD Probe
**File:** `merid/diagnostics/ws_raw_vs_parsed.py`

**Purpose:** Confirm whether Kalshi is actually sending MD for these channels and whether the parser is discarding it.

**What it checks:**
- Hooks into WS client to count per-minute:
  - Total messages received
  - Messages per market ID
  - Messages that successfully parsed into orderbook update
  - Messages that were rejected/errored with reasons
- Logs WS_RAW_SUMMARY with parse success/fail rates
- For each active ticker: "msgs_received" and "book_last_update_age"

**Why it helps:**
- If messages for "wrong" tickers: catalog/WS subscription is wrong
- If messages for right tickers but 0 parse successes: parser is wrong
- If 0 raw messages for supposedly subscribed markets: WS channel is wrong

**Note:** Requires integration with WS client to track message counts. The `WSTrafficTracker` class is provided for this integration.

**HTTP Endpoint:** `/diagnostics/ws_raw_vs_parsed`

---

### 4. Market State Age Distribution Probe
**File:** `merid/diagnostics/market_state_health_distribution.py`

**Purpose:** See *how many* markets across the store have stale or never-initialized orderbooks.

**What it checks:**
- Iterates over *all* `KalshiMarketStateStore` entries (not just 5 "current")
- For each state: `market_id`, `asset`, `series`, `book_init` flag, `last_update_ts`
- Derives `md_age = now_utc - last_update`
- Aggregates stats per asset and overall
- Prints histogram/bins of MD age (0-30s, 30-60s, 60-300s, >300s)

**Why it helps:**
- Tells if problem is "only current window is bad" or "entire history is dead"
- Shows whether a few markets are healthy or *none* are

**HTTP Endpoint:** `/diagnostics/market_state_health`

---

### 5. Ticker Inference vs Close_ts Authority Check
**File:** `merid/diagnostics/ticker_inference_vs_close_ts.py`

**Purpose:** Explicitly demonstrate where ticker-based inference diverges from Kalshi epoch truth.

**What it checks:**
- For each market in catalog:
  - Computes `close_time_from_ts` via `close_ts`
  - Computes `close_time_from_ticker` using current parsing function
  - Prints difference `delta = close_time_from_ts - close_time_from_ticker`
- Summarizes: number with `delta = 0`, `|delta| > 1s`, `>60s`, etc.
- Shows example tickers with largest deltas

**Why it helps:**
- Quantifies how bad "ticker-based expiry inference" really is
- Gives hard data to justify ripping out ticker-derived time everywhere

**HTTP Endpoint:** `/diagnostics/ticker_inference`

---

### 6. Active vs Truly Live Probe
**File:** `merid/diagnostics/active_vs_truly_live.py`

**Purpose:** For each asset, prove whether your "active" market is actually live on Kalshi, using only REST and `close_ts`.

**What it checks:**
- For each asset series:
  - Uses Script 1's logic to pick the **live** market by `close_ts`
  - Uses current production logic to pick the "active" market
- Queries Kalshi REST for both market IDs
- Checks status fields (`status`, `is_active`, `settlement`, etc.)

**Why it helps:**
- If prod consistently picks markets whose REST status is "closed/settled": selection is broken
- If both prod and ts-based pick same but REST says "active": problem is purely in WS/MD

**HTTP Endpoint:** `/diagnostics/active_vs_live`

---

### 7. Agent Grid + Signal Path Probe
**File:** `merid/diagnostics/agent_grid_and_signals.py`

**Purpose:** Inspect the live agent grid to check if agents are operating on correct markets and have access to required data.

**What it checks:**
- Asks `get_agent_grid()` from live server (same singleton used by loop)
- For each asset agent (BTC, ETH, SOL, XRP, DOGE):
  - Confirms `agent is not None`
  - Checks if agent sees current market
  - Checks if agent has current spot
  - Checks if MD is marked healthy
  - Gets last signal time

**Why it helps:**
- Shows whether agents are operating on "phantom" markets or missing MD
- Consistent with rest of system diagnostics

**HTTP Endpoint:** `/diagnostics/agent_grid`

---

### 8. Server-Integrated Singleton Access Harness
**File:** `merid/diagnostics/router.py`

**Purpose:** Common diagnostic harness that executes code against the server's real singletons via HTTP endpoints.

**What it provides:**
- FastAPI router with endpoints for each diagnostic
- `/diagnostics/` - lists all available diagnostics
- `/diagnostics/time_alignment` - runs time alignment probe
- `/diagnostics/catalog_ws_md_consistency` - runs catalog/WS/MD consistency probe
- `/diagnostics/ws_raw_vs_parsed` - runs WS traffic probe
- `/diagnostics/market_state_health` - runs market state health probe
- `/diagnostics/ticker_inference` - runs ticker inference probe
- `/diagnostics/active_vs_live` - runs active vs live probe
- `/diagnostics/agent_grid` - runs agent grid probe
- `/diagnostics/all` - runs all diagnostics and returns combined results

**Why it helps:**
- Guarantees always introspecting the live instance, not a fresh one
- Makes trivial to add new probes without re-plumbing access
- Enables CLI scripts to call diagnostics via HTTP instead of importing core classes

**Integration Required:**
The router must be integrated into the main FastAPI application:
```python
from merid.diagnostics.router import router as diagnostics_router
app.include_router(diagnostics_router)
```

---

## Prioritized Fix List Framework

Based on probe results, fixes should be prioritized in this order:

### Priority 1: Time Authority & Skew
**Probes:** Script 1 + Script 5

**What to look for:**
- `close_ts` and ticker parsing disagree
- `now_utc` is not real UTC
- Time skew between server and Kalshi

**Impact:** If time is wrong, ALL market selection is wrong.

**Fix actions:**
1. Replace all ticker-based time inference with `close_ts`-based computation
2. Verify server clock is synchronized with NTP
3. Ensure all time comparisons use timezone-aware UTC datetimes

---

### Priority 2: Active Window Selection
**Probes:** Script 6

**What to look for:**
- Production picking expired/future markets vs Kalshi truth
- Catalog active markets have REST status "closed/settled"

**Impact:** Trading on wrong or expired markets.

**Fix actions:**
1. Update catalog `get_active_markets()` to use `close_ts`-based filtering
2. Remove ticker-based expiry inference
3. Add validation that selected markets are actually live via REST

---

### Priority 3: Catalog vs WS vs MD Coherence
**Probes:** Script 2 + Script 4

**What to look for:**
- Subscription set diverges from catalog
- MD is stale or never initialized
- Few or no markets have healthy orderbooks

**Impact:** WS not subscribed to right markets, or MD not updating.

**Fix actions:**
1. Ensure WS subscription logic uses same market selection as catalog
2. Fix MD update pipeline if parsing is failing
3. Investigate why orderbooks are not being populated

---

### Priority 4: WS Ingestion Pipeline
**Probes:** Script 3

**What to look for:**
- Raw messages exist but not populating MD
- Nothing coming in at all
- Parse failures with specific reasons

**Impact:** No market data flowing into system.

**Fix actions:**
1. If 0 raw messages: Fix WS channel subscription
2. If messages for wrong tickers: Fix subscription logic
3. If messages for right tickers but 0 parse successes: Fix parser
4. Integrate `WSTrafficTracker` into WS client for ongoing monitoring

---

### Priority 5: Agent Grid / Signal Consistency
**Probes:** Script 7

**What to look for:**
- Agents operating on phantom markets
- Agents missing MD or spot data
- Safety gates blocking signal generation

**Impact:** Trading logic operating on wrong assumptions or blocked.

**Fix actions:**
1. Ensure agents use same market selection as catalog
2. Fix agent data access if missing MD/spot
3. Review safety gate logic if blocking legitimate signals

---

## Running the Diagnostics

### Via HTTP (Recommended)

Run all diagnostics:
```bash
curl http://localhost:8011/diagnostics/all
```

Run specific diagnostic:
```bash
curl http://localhost:8011/diagnostics/time_alignment
curl http://localhost:8011/diagnostics/catalog_ws_md_consistency
```

### Via CLI (Standalone)

Run diagnostic directly (creates new instances, not recommended for live server introspection):
```bash
python -m merid.diagnostics.time_alignment
python -m merid.diagnostics.catalog_ws_md_consistency
```

## Integration Steps

1. **Integrate diagnostics router into main FastAPI app:**
   ```python
   from merid.diagnostics.router import router as diagnostics_router
   app.include_router(diagnostics_router)
   ```

2. **Integrate WSTrafficTracker into WebSocket client:**
   - Import `get_ws_tracker()` in WS client
   - Call `tracker.record_message(market_id)` on each raw message
   - Call `tracker.record_parse_success(market_id)` on successful parse
   - Call `tracker.record_parse_failure(market_id, reason)` on parse failure

3. **Add health_snapshot() method to agents:**
   - Implement side-effect-free method that returns agent state
   - Include current market, spot, MD health, last signal time

4. **Run diagnostics and analyze results:**
   - Start server
   - Call `/diagnostics/all`
   - Review results against prioritized fix list
   - Implement fixes in priority order
   - Re-run diagnostics to verify fixes

## Expected Outcomes

When all diagnostics pass:
- Time alignment: catalog and TS-based selection match for all assets
- Catalog/WS/MD: all three layers track same tickers
- WS traffic: messages received for correct tickers, parse success rate > 95%
- Market state health: current window markets have MD age < 30s
- Ticker inference: delta = 0 for all markets (or ticker inference removed)
- Active vs live: production and TS-based pick same market, REST status = "active"
- Agent grid: all agents loaded, see market/spot/MD, health status = "HEALTHY"
