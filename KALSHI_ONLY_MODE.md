# Kalshi-Only Mode

**Purpose:** Focus MERID's UI and backend on Kalshi prediction markets only, preventing scope drift and ensuring clean end-to-end wiring for agent/swarm trading.

---

## Canonical Kalshi-Only Views

The following **8 views** are marked `kalshi_only=True` in `merid/ui_views_manifest.py`:

### **Markets / Trading**
1. **`predictions`** — PRIMARY Kalshi view: US-compliant markets + drift signals
2. **`prediction-consensus`** — Swarm Brain: consensus opinions, plans, instruments

### **Portfolio**
3. **`overview`** — Portfolio summary with reconciliation badges
4. **`positions`** — Position table filtered to Kalshi venue

### **Signals**
5. **`signal-layer`** — Kalshi-specific signals: arbs, drift, macro, CQI

### **Ops / Risk**
6. **`operator`** — PRIMARY reconciliation view: audit trail + system status
7. **`risk`** — Risk metrics and alerts for Kalshi venue
8. **`health`** — System/venue health including Kalshi adapter

---

## Implementation

### **1. Manifest Flag (`merid/ui_views_manifest.py`)**

Each `ViewConfig` now has a `kalshi_only` boolean field:

```python
ViewConfig(
    id="predictions",
    route="predictions",
    title="Prediction Markets",
    kalshi_only=True,  # Marks view as Kalshi-focused
    components=[...],
)
```

**All other views** (betting, crypto trading, flow-radar, etc.) remain `kalshi_only=False` by default.

---

### **2. TypeScript Manifest (`web/react/src/config/uiViewsManifest.ts`)**

Auto-generated from Python manifest via:

```bash
python scripts/generate_ts_manifest.py
```

TypeScript interface includes `kalshiOnly` field:

```typescript
export interface ViewConfig {
  id: string;
  route: string;
  title: string;
  kalshiOnly: boolean;  // New field
  components: ComponentBinding[];
}

// Helper function to filter Kalshi-only views
export function kalshiOnlyViews(): ViewConfig[] {
  return VIEWS.filter((v) => v.kalshiOnly);
}
```

---

### **3. React Sidebar Filter**

To enable Kalshi-only sidebar filtering:

```typescript
// In sidebar config or App.tsx
import { allViews, kalshiOnlyViews } from './config/uiViewsManifest';

const KALSHI_ONLY = import.meta.env.VITE_KALSHI_ONLY === 'true';

const visibleViews = KALSHI_ONLY ? kalshiOnlyViews() : allViews;
```

**Enforcement with tests** (add to `web/react/src/components/__tests__/Sidebar.test.tsx`):

```typescript
import { render, screen } from '@testing-library/react';
import Sidebar from '../Sidebar';
import { kalshiOnlyViews } from '@/config/uiViewsManifest';

describe('Sidebar - Kalshi-only mode', () => {
  it('shows only kalshi_only views when KALSHI_ONLY=true', () => {
    process.env.VITE_KALSHI_ONLY = 'true';
    
    const { container } = render(<Sidebar />);
    const kalshiViews = kalshiOnlyViews();
    
    // Should show exactly 8 Kalshi views
    expect(kalshiViews).toHaveLength(8);
    
    // Check each expected view is present
    kalshiViews.forEach(view => {
      expect(container).toHaveTextContent(view.title);
    });
    
    // Non-Kalshi views should NOT appear
    expect(container).not.toHaveTextContent('Betting Markets');
    expect(container).not.toHaveTextContent('Flow Radar');
  });
  
  it('shows all views when KALSHI_ONLY=false', () => {
    process.env.VITE_KALSHI_ONLY = 'false';
    
    const { container } = render(<Sidebar />);
    
    // Should include both Kalshi and non-Kalshi views
    expect(container).toHaveTextContent('Prediction Markets');
    expect(container).toHaveTextContent('Betting Markets');
  });
});
```

Current sidebar at `web/react/src/components/Sidebar.tsx` is already Kalshi-focused with hardcoded views.

---

### **4. Backend Venue Guards (`merid/venue_registry.py`)**

`VenueRegistry` methods now support `kalshi_only` parameter:

```python
# Get positions only from Kalshi venue
positions = await registry.get_all_positions(kalshi_only=True)

# Get risk snapshots only from Kalshi venue
risk = await registry.get_all_risk_snapshots(kalshi_only=True)
```

**Enforcement:**
- `kalshi_only=True` → restricts to `venues=["kalshi"]`
- Ignores any other venues parameter
- Prevents accidental cross-venue data leaks

---

### **5. API Endpoints (Backend Integration)**

Add `KALSHI_ONLY` mode to endpoints used by Kalshi-only views:

```python
# In web/api endpoints or merid/settings.py
import os

KALSHI_ONLY = os.getenv("KALSHI_ONLY", "false").lower() == "true"

# Example: positions endpoint
@router.get("/api/v1/positions")
async def get_positions():
    from merid.venue_registry import get_venue_registry
    registry = get_venue_registry()
    return await registry.get_all_positions(kalshi_only=KALSHI_ONLY)
```

---

### **6. Test Suite (`tests/test_kalshi_only_views.py`)**

Comprehensive tests ensure:
- ✅ Exactly 8 views marked `kalshi_only=True`
- ✅ All Kalshi views use venue_registry (no direct Kalshi API calls)
- ✅ Consensus views use consensus_bridge
- ✅ Reconciliation views use reconciliation module
- ✅ `kalshi_only` parameter filters venues correctly
- ✅ No Kalshi API URLs leak into view definitions

**Run tests:**
```bash
pytest tests/test_kalshi_only_views.py -v
```

---

## Environment Configuration

Set `KALSHI_ONLY` mode via environment variable:

```bash
# Backend (.env)
KALSHI_ONLY=true

# Frontend (.env.local)
VITE_KALSHI_ONLY=true
```

---

## Wiring Contract

All `kalshi_only` views **must**:

1. **Use venue_registry** — Never call Kalshi REST API directly
2. **Use consensus_bridge** — For swarm opinions, plans, votes (predictions/signal-layer)
3. **Use reconciliation module** — For audit trail, discrepancies (operator/risk)
4. **Respect paper mode** — Route through paper venue adapter when `PAPER_MODE=true`

---

## Non-Kalshi Views

The following views are **excluded** from Kalshi-only mode (`kalshi_only=False`):

### **Crypto / Other Venues**
- `trading` (crypto domain)
- `tradefloor` (crypto domain)
- `flow-radar` (flow detection)

### **Betting Markets**
- `betting`
- `betting-consensus`

### **General / Dev Tools**
- `wallet`, `treasury` (general finance)
- `agents`, `devswarm` (agent management)
- `rewards`, `social`, `plugins`, `analytics`, `api`, `logs`

These views can be **hidden** in Kalshi-only builds or kept visible for multi-venue support.

---

## Migration Checklist

### ✅ **Completed**
- [x] Add `kalshi_only` field to `ViewConfig` dataclass
- [x] Mark 8 core Kalshi views with `kalshi_only=True`
- [x] Update TypeScript generator to include `kalshiOnly` field
- [x] Add `kalshi_only` parameter to `venue_registry.get_all_positions()`
- [x] Add `kalshi_only` parameter to `venue_registry.get_all_risk_snapshots()`
- [x] Create `tests/test_kalshi_only_views.py` with wiring assertions

### 🔄 **Next Steps**
- [ ] Regenerate TypeScript manifest: `python scripts/generate_ts_manifest.py`
- [ ] Add `KALSHI_ONLY` env var to backend settings
- [ ] Wire `/api/v1/positions` endpoint to use `kalshi_only` parameter
- [ ] Wire `/api/v1/portfolio/summary` endpoint to use `kalshi_only` parameter
- [ ] Wire `/api/v1/risk/metrics` endpoint to use `kalshi_only` parameter
- [ ] Run test suite: `pytest tests/test_kalshi_only_views.py -v`
- [ ] (Optional) Update React sidebar to filter by `kalshiOnlyViews()`

---

## Usage Examples

### **Python Backend**
```python
from merid.ui_views_manifest import VIEWS, views_for_section

# Get all Kalshi-only views
kalshi_views = [v for v in VIEWS if v.kalshi_only]
print(f"Kalshi-only views: {[v.id for v in kalshi_views]}")

# Get Kalshi positions only
from merid.venue_registry import get_venue_registry
registry = get_venue_registry()
positions = await registry.get_all_positions(kalshi_only=True)
```

### **TypeScript Frontend**
```typescript
import { kalshiOnlyViews } from '@/config/uiViewsManifest';

const kalshiViews = kalshiOnlyViews();
console.log('Kalshi-only views:', kalshiViews.map(v => v.id));

// Render only Kalshi views in sidebar
{kalshiViews.map(view => (
  <NavItem key={view.id} view={view} />
))}
```

---

## Benefits

1. **No scope drift** — Clear boundary: only 8 views are Kalshi-specific
2. **Testable contract** — Test suite enforces venue_registry/consensus_bridge usage
3. **Clean separation** — Non-Kalshi features can evolve independently
4. **Easy audit** — `kalshi_only=True` flag makes Kalshi surfaces explicit
5. **Mode switching** — Toggle `KALSHI_ONLY` env var to enable/disable multi-venue

---

## Change Protocol

**⚠️ CRITICAL: The Kalshi-only surface is FROZEN at 8 views to prevent scope creep.**

### To Add a New Kalshi View

You **MUST** complete all 4 steps:

1. **Update `EXPECTED_KALSHI_VIEWS` in `tests/test_kalshi_only_views.py`**
   - Add the view ID to the frozen set
   - CI will fail if you skip this step

2. **Mark view with `kalshi_only=True` in `merid/ui_views_manifest.py`**
   ```python
   ViewConfig(
       id="new_view",
       kalshi_only=True,  # Must be explicitly marked
       components=[...],
   )
   ```

3. **Document justification in this file (KALSHI_ONLY_MODE.md)**
   - Add one sentence explaining why this view exists
   - Example: "9. **`kalshi-analytics`** — Real-time Kalshi market analytics dashboard"

4. **Ensure view uses proper modules**
   - `venue_registry` for positions/orders/markets
   - `consensus_bridge` for swarm opinions/votes
   - `reconciliation` for audit trail/discrepancies
   - Never call Kalshi REST API directly

**Test enforcement:**
```bash
pytest tests/test_kalshi_only_views.py::TestKalshiOnlyManifest::test_kalshi_only_view_ids_are_exact -v
```

### To Modify an Existing Kalshi View's Backend

All backend changes **MUST**:
- Route through `venue_registry`, `consensus_bridge`, or `reconciliation` only
- Never bypass the venue adapter to call Kalshi API directly
- Respect `kalshi_only` parameter in data queries

**Test enforcement:**
```bash
pytest tests/test_kalshi_only_views.py::TestNoDirectKalshiAPICalls::test_no_direct_kalshi_http_calls_in_codebase -v
```

### To Add a Non-Kalshi View

Non-Kalshi views are **unrestricted**:
- Leave `kalshi_only=False` (default)
- No changes to `EXPECTED_KALSHI_VIEWS` needed
- Can use any backend module

---

## Guardrails Summary

The following tests **prevent scope creep**:

1. **`test_kalshi_only_view_ids_are_exact`** — Frozen set of 8 view IDs, fails on any change
2. **`test_no_direct_kalshi_http_calls_in_codebase`** — Repo-wide grep for Kalshi URLs
3. **`test_positions_endpoint_restricts_to_kalshi`** — Venue filtering at API level
4. **`test_kalshi_views_use_merid_api_paths`** — All paths start with `/api/`

**Run full suite:**
```bash
pytest tests/test_kalshi_only_views.py -v
```

---

## Agent Instructions

When using AI agents (OpenClaw, Claude, etc.) on MERID:

**Prepend this to system prompt:**

> You are working on MERID's Kalshi-only mode. The Kalshi UI surface is FROZEN at exactly 8 views:
> - `predictions`, `prediction-consensus`, `overview`, `positions`, `signal-layer`, `operator`, `risk`, `health`
>
> **Hard rules:**
> 1. You may NOT add new Kalshi views without updating `EXPECTED_KALSHI_VIEWS` and documenting justification
> 2. All Kalshi data MUST flow through `venue_registry`, `consensus_bridge`, or `reconciliation` modules
> 3. NEVER call Kalshi API directly — use the venue adapter pattern
> 4. When touching Kalshi views, verify changes pass: `pytest tests/test_kalshi_only_views.py -v`
>
> Any attempt to add views or bypass adapters will fail CI.

---

## Maintenance

When adding **new Kalshi views** (rare):
1. Follow the Change Protocol above (all 4 steps required)
2. Get explicit approval before expanding the frozen set

When adding **new non-Kalshi views**:
- Leave `kalshi_only=False` (default)
- No additional changes needed

---

## Related Files

- `merid/ui_views_manifest.py` — Python source of truth
- `scripts/generate_ts_manifest.py` — TS generator script
- `web/react/src/config/uiViewsManifest.ts` — Auto-generated TS manifest
- `merid/venue_registry.py` — Venue adapter with `kalshi_only` guards
- `tests/test_kalshi_only_views.py` — Wiring test suite
- `web/react/src/components/Sidebar.tsx` — React sidebar component

---

## Infrastructure Implementation (Backend)

### **Startup Command**

**CRITICAL:** You must use the factory pattern to allow feature gates to work:

```bash
# ✅ CORRECT - Uses factory pattern
make serve

# OR manually:
py -m uvicorn web.main:create_app --factory --host 0.0.0.0 --port 8000 --reload

# ❌ WRONG - Imports at module level before gates can run
py -m uvicorn web.main:app --reload --port 8000
```

The `--factory` flag tells uvicorn to call `create_app()` during startup, not at import time. This allows `settings.KALSHI_ONLY` checks to gate imports properly.

---

### **Feature Gates Implemented**

#### **1. Crypto Exchange Initialization**

**File:** `data/live_price_feed.py:100-106`

```python
def _initialize_exchanges(self):
    """Initialize exchange connections with real API keys and retry logic."""
    # Skip crypto exchanges in Kalshi-only mode
    from merid.settings import settings
    if settings.KALSHI_ONLY:
        logger.info("Crypto exchanges SKIPPED (Kalshi-only mode)")
        return
    # ... rest of initialization
```

**Result:** When `KALSHI_ONLY=True`, no Kraken, Coinbase, Gemini, Binance, Bybit, or Okx connections are made.

---

#### **2. Phase0 Minimal Scope**

**File:** `merid/settings.py:220`

```python
PHASE0_ENABLED: bool = Field(default=False, description="Enable Phase0 minimal crypto scope")
```

**File:** `web/main.py:197-201` (routers commented out)

```python
# Phase0 routers - lazy import based on PHASE0_ENABLED flag
# from web.api.minimal_scope import router as minimal_scope_router
# from web.api.phase0_experiment import router as phase0_experiment_router
# from web.api.phase0_adapters import phase0_router
# from web.api.phase0_trial_api import router as phase0_trial_router
```

**Result:** Phase0 APIs and crypto model governance disabled by default.

---

#### **3. Trading Suite Router**

**File:** `web/main.py:150-151` (lazy import)

```python
# Lazy import - trading_suite loads paper adapter which instantiates at module level
# from web.api.trading_suite import router as trading_suite_router
```

**File:** `web/main.py:425-427` (conditional registration)

```python
if not _kalshi_only:
    from web.api.trading_suite import router as trading_suite_router
    application.include_router(trading_suite_router, prefix="/api/v1/trading-suite", tags=["trading-suite"])
```

**Result:** Trading suite (crypto paper trading) only loads in full mode, not Kalshi-only.

---

#### **4. Polymarket Integration**

**File:** `merid/settings.py:225`

```python
MERID_ENABLE_POLYMARKET: bool = Field(default=False, description="Enable Polymarket integration")
```

**Result:** Polymarket disabled by default in Kalshi-only deployments.

---

### **Environment Configuration**

**Required Settings for Kalshi-Only Mode:**

```bash
# .env or environment
KALSHI_ONLY=true
MERID_PROFILE=kalshi-only

# Kalshi API credentials
KALSHI_API_KEY_ID=your_key_id
KALSHI_PRIVATE_KEY_PATH=/path/to/kalshi_private_key.pem
# OR
KALSHI_PRIVATE_KEY_PEM="-----BEGIN PRIVATE KEY-----..."

# Trading mode
MERID_PM_TRADING_MODE=paper  # or 'live' for real trading
MERID_PM_LIVE_ENABLED=false  # Set to true for live mode
```

---

### **Startup Log Verification**

**✅ Clean Kalshi-Only Startup Should Show:**

```
2026-02-18 05:31:22 | INFO | agents.reflection | Loaded 3716 reflections for 7 agents
2026-02-18 05:31:23 | INFO | memory.neo4j_graph | ✅ Neo4j connected
2026-02-18 05:31:23 | INFO | data.live_price_feed | Crypto exchanges SKIPPED (Kalshi-only mode)
2026-02-18 05:31:32 | INFO | web.main | Paper trading engine SKIPPED (Kalshi-only mode)
2026-02-18 05:31:32 | INFO | merid.prediction.agent_grid | AgentGrid initialized: 24 agents
2026-02-18 05:31:32 | INFO | merid.event_venues.kalshi.client | [kalshi] Initializing new HTTP client
```

**❌ Should NOT See:**

```
Kraken exchange initialized
Coinbase exchange initialized
Alpaca REST client
PaperTradingEngine subscribed to live price feed
Phase0 minimal scope initialized
```

---

### **Router Gating in web/main.py**

Crypto-related routers are conditionally imported based on `_kalshi_only` flag:

```python
_kalshi_only = _profile in ("kalshi-only", "kalshi_only", "kalshi")

# Gated routers (lines 370-425)
if not _kalshi_only:
    from web.api.trading import router as trading_router
    from web.api.paper_trading import router as paper_trading_router
    from web.api.arbitrage import router as arbitrage_router
    # ... other crypto/phase0 routers
```

**Kalshi routers always loaded:**
- `/api/v1/kalshi/*` - Kalshi market data and execution
- `/api/v1/operator/*` - Operator dashboard and risk
- `/api/agents/*` - Agent grid status
- `/api/v1/portfolio/*` - Portfolio summary (Kalshi-filtered)
- `/api/v1/risk/*` - Risk metrics and alerts
- `/api/v1/system/*` - System health

---

### **Runtime Trading Config**

**File:** `merid/settings.py:165-174`

```python
# Prediction market settings (Kalshi-first)
KALSHI_ONLY: bool = Field(default=True, description="Kalshi-only mode")
MERID_PM_TRADING_MODE: str = Field(default="sim", description="PM mode: sim/paper/live")
MERID_PM_LIVE_ENABLED: bool = Field(default=False, description="Explicit unlock for live PM")
MERID_PM_MAX_NOTIONAL_PER_MARKET: float = Field(default=500.0, description="Max per market")
MERID_PM_MAX_DAILY_LOSS: float = Field(default=250.0, description="Max daily loss")
MERID_PM_MAX_TOTAL_NOTIONAL: float = Field(default=5000.0, description="Max total notional")
```

**VenueGate Configuration:**

The `merid.prediction.venue_gate.VenueGate` respects these settings:
- `mode=sim` → No real orders, simulation only
- `mode=paper` → Paper trading with mock fills
- `mode=live` → Real Kalshi orders (requires `MERID_PM_LIVE_ENABLED=true`)

---

### **Agent Grid Configuration**

**File:** `merid/prediction/agent_grid_config.py`

24 Kalshi trading agents are initialized covering:
- **Assets:** BTC, ETH, SOL, XRP, DOGE
- **Timeframes:** 15m, 1h, daily, weekly
- **Archetypes:** directional, reversion, momentum, volatility, correlation

All agents use:
- `kalshi_tools` for market data/execution
- `venue_gate` for paper/live mode routing
- `portfolio_risk_agent` for position limits

---

### **Troubleshooting**

**Issue:** Crypto exchanges still initializing

**Solution:**
1. Verify `KALSHI_ONLY=true` in `.env`
2. Use correct startup command: `make serve` or `uvicorn ... --factory`
3. Check logs for "Crypto exchanges SKIPPED"

---

**Issue:** Phase0 routers still mounting

**Solution:**
1. Verify Phase0 imports are commented out in `web/main.py:197-201`
2. Set `PHASE0_ENABLED=false` in `.env`

---

**Issue:** Paper trading engine starting

**Solution:**
1. Verify conditional gate at `web/main.py:1831-1844`
2. Check for "Paper trading engine SKIPPED" in logs

---

**Last Updated:** 2026-02-18  
**Status:** ✅ Infrastructure gating complete, use `make serve` to start
