# MERID Agent-Level Wiring Audit

**Date:** 2026-04-11  
**Scope:** Kalshi Prediction Market Execution Path  
**Goal:** Identify which components can turn a "trade idea" into a live Kalshi order vs. which are purely analytical.

---

## Executive Summary

### Target Architecture: Single Executor Principle

There is exactly **ONE** agent-level executor responsible for sending live orders to Kalshi:

> **KalshiTradingAgent (via `kalshi_tools` → `route_order_async`)** is the only module allowed to actually send orders. All strategies, signals, and drivers must route through this path to avoid duplication and fragmented risk control.

This ensures:
- Unified risk gate (sanity, exposure, kill switches)
- Single fills ledger for PnL attribution
- Tamper-evident audit trail
- No split-brain order state

---

### Critical Finding: TWO Execution Paths Exist (Violation of Single Executor)

| Path | Router? | Executor? | Status |
|------|---------|-----------|--------|
| **KalshiTradingAgent** → `route_order_async()` | ✅ Yes | ✅ Yes (Canonical) | **Authorized** |
| **KalshiContinuousTrader** → `self._post()` | ❌ No | ✅ Yes (Direct HTTP) | **BYPASS — Migration in Progress** |

**CT bypasses:** sanity check, fills integrity validation, stale snapshot guard, unified audit logging.

**Acceptance Criterion:** This audit is complete when the Bypass List is **empty** and all execution flows are via the canonical router.

---

## 1. Static Analysis: Order Router Entrypoints

### Canonical Router Functions

| Function | Location | Purpose | Async |
|----------|----------|---------|-------|
| `route_order_async()` | `merid/event_venues/kalshi/order_router.py:850` | Primary async entrypoint for all Kalshi orders | Yes |
| `route_order()` | `merid/event_venues/kalshi/order_router.py:860` | Sync wrapper (calls async via `asyncio.run`) | No |
| `simulate_paper_fill()` | `merid/event_venues/kalshi/order_router.py:317` | Paper/mock fill simulation | No |

### Direct Kalshi Client Calls (CI Whitelist Required)

| Location | Call Pattern | Status |
|----------|--------------|--------|
| `merid/trading/kalshi_continuous_trader.py:3445` | `self._post("/portfolio/orders", order_data)` | **⚠️ NOT IN WHITELIST** |
| `merid/prediction/kalshi_tools.py:435` | `route_order_async(intent)` | ✅ Canonical |
| `merid/prediction/trading_agent.py:2055` | `route_order_async(_ioc_intent)` | ✅ Canonical (stop-loss) |

---

## 2. Agent Call Graph Analysis

### 2.1 KalshiTradingAgent (Full Chain)

```
KalshiTradingAgent (per-asset/timeframe agent)
├── run_cycle()                           ← Public entry
│   └── _run_cycle_body()
│       ├── _resolve_markets()            ← Market discovery
│       ├── _filter_active_contracts()    ← Entry window filtering
│       ├── _build_snapshot()             ← Market data + sentiment
│       ├── KalshiStrategy.evaluate()     ← Edge/sizing computation
│       ├── _risk.check_order()           ← Pre-trade risk check
│       └── _execute_signal()             ← Order dispatch
│           ├── _kalshi_place_order()    ← Via kalshi_tools
│           │   └── route_order_async()  ← CANONICAL ROUTER
│           └── OR stop-loss path:
│               └── route_order_async()  ← Direct router call
```

**Capabilities:**
- ✅ Computes edge: Yes (via `KalshiStrategy`)
- ✅ Builds orders: Yes (`OrderIntent` with all metadata)
- ✅ Can hit router: Yes (via `kalshi_tools._kalshi_place_order`)
- 🛡️ Gate: Requires `LifecycleState.ACTIVE`, risk check pass, not in warmup

### 2.2 KalshiContinuousTrader (Separate Universe)

```
KalshiContinuousTrader (singleton, multi-asset)
├── run()                                 ← Async loop
│   └── _run_cycle() (in executor thread)
│       └── _run_cycle_inner()
│           ├── _get_all_spots()          ← Spot price fetch
│           ├── FilterPipeline.filter()   ← Market discovery
│           ├── _compute_edge()           ← Edge computation
│           ├── bankroll.calculate_order_size()  ← Kelly sizing
│           ├── KalshiRiskManager.check_order() ← Risk gate
│           └── self._post("/portfolio/orders") ← DIRECT HTTP
```

**Capabilities:**
- ✅ Computes edge: Yes (custom logistic model)
- ✅ Builds orders: Yes (dict with `client_order_id`, `group_id`)
- ⚠️ Can hit router: **NO** — uses direct `_post()` to Kalshi REST API
- 🛡️ Gates: `execution_gate`, `risk_controller`, `KalshiRiskManager`, per-asset caps

### 2.3 Consensus Bridge (Analytical Only)

```
KalshiConsensusAdapter
├── signal_to_energy()                    ← Converts to energy packet
└── order_intent_to_vote()                ← Converts to vote
```

**Capabilities:**
- ✅ Computes edge: No (translates existing signals)
- ❌ Builds orders: No (outputs energy/vote packets)
- ❌ Can hit router: **NO** (consensus layer only)

### 2.4 Other Agents (via Tool Registry)

| Agent/Module | Evaluates Edge? | Builds Orders? | Can Hit Router? | Path |
|--------------|-----------------|----------------|-----------------|------|
| `DiscoverAgent` (market_catalog) | No | No | No | Read-only discovery |
| `AnalyzeAgent` (strategy) | Yes | Yes (signal) | No | Signal only, no execution |
| `ConsensusAgent` (coordinator) | Yes | No | No | Aggregate opinions |
| `PortfolioRiskAgent` | No | No | No | Risk monitoring only |
| `BTC15mLane` | Yes | Yes | No | Lane-specific sizing, no direct router |
| `Crypto15mLane` | Yes | Yes | No | Lane-specific sizing, no direct router |

---

## 3. Agent Classification Table

| Agent / Module | Evaluates Edge? | Builds Orders? | Can Hit Router? | Router Path Used | Notes |
|----------------|-----------------|----------------|-----------------|-------------------|-------|
| **KalshiTradingAgent** | ✅ Yes | ✅ Yes | ✅ Yes | `kalshi_tools._kalshi_place_order → route_order_async()` | **Canonical Executor** — Single source of truth for order execution |
| **KalshiContinuousTrader** | ✅ Yes | ⚠️ **Signal only** (target) | ❌ **NO** (must use executor) | ~~Direct `self._post()`~~ → *Migration to adapter* | **In Migration** — Demoting from executor to strategy driver (Section 7) |
| **KalshiConsensusAdapter** | ❌ No (translates) | ❌ No | ❌ No | N/A | Analytical bridge only |
| **DiscoverAgent** | ❌ No | ❌ No | ❌ No | N/A | Market discovery only |
| **AnalyzeAgent** (strategy) | ✅ Yes | ⚠️ Signal only | ❌ No | N/A | Computes edge, doesn't execute |
| **PortfolioRiskAgent** | ❌ No | ❌ No | ❌ No | N/A | Risk monitoring & alerts |
| **ConsensusAgent** (TaCo) | ✅ Yes | ❌ No | ❌ No | N/A | Opinion aggregation |
| **BTC15mLane** | ✅ Yes | ✅ Yes | ✅ Yes (via agent) | Uses TradingAgent tools | Lane wrapper — delegates to canonical executor |
| **Crypto15mLane** | ✅ Yes | ✅ Yes | ✅ Yes (via agent) | Uses TradingAgent tools | Lane wrapper — delegates to canonical executor |
| **SocialBroadcaster** | ❌ No | ❌ No | ❌ No | N/A | Telemetry/alerting only |

---

## 4. CI Venue-Touchpoint Guard Analysis

### Current Whitelist (`/.ci/venue_touchpoint_whitelist.txt`)

```
scripts/migrate_positions_legacy.py       # One-time migration
scripts/manual_order_correction.py        # Admin manual tool
scripts/emergency_kill_and_flatten.py     # Emergency (with --manual flag)
scripts/admin_position_adjustment.py      # Admin manual tool
```

### Findings

| File | Direct Kalshi Call? | In Whitelist? | Risk Level |
|------|---------------------|---------------|------------|
| `merid/trading/kalshi_continuous_trader.py:3445` | `self._post("/portfolio/orders")` | **NO** | 🔴 **HIGH** |
| `merid/prediction/kalshi_tools.py:435` | `route_order_async()` (canonical) | N/A (uses router) | 🟢 Low |
| `merid/event_venues/kalshi/client.py` | Direct HTTP client | N/A (abstract client) | 🟡 Medium |

**Issue:** `kalshi_continuous_trader.py` makes direct HTTP calls to Kalshi that bypass the canonical `order_router`. This is **NOT captured** by the current whitelist which only checks for direct `place_order` calls on the Kalshi client.

---

## 5. Execution Chain Depth Analysis

### Full Chain from Signal to Fill

#### Path A: KalshiTradingAgent (Canonical)
```
1. Signal generation (StrategySignal)
2. Risk check (_risk.check_order)
3. Execution dispatch (_execute_signal)
4. Tool invocation (_kalshi_place_order)
5. **OrderIntent construction**
6. **route_order_async()** ← ROUTER ENTRY
7. Mode resolution (paper/live)
8. Live: KalshiVenueClient.place_order()
9. Fill recording (fills_ledger)
```

#### Path B: KalshiContinuousTrader (Direct)
```
1. Edge computation (_compute_edge)
2. Bankroll sizing (calculate_order_size)
3. Risk check (KalshiRiskManager.check_order) ← DIFFERENT risk gate
4. **Order dict construction**
5. **self._post("/portfolio/orders")** ← DIRECT HTTP
6. Fill recording (self.tracker.record_order)
```

### Key Differences

| Aspect | KalshiTradingAgent | KalshiContinuousTrader |
|--------|-------------------|----------------------|
| Router used | ✅ `route_order_async()` | ❌ Direct HTTP |
| Risk gate | `PredictionMarketRisk` | `KalshiRiskManager` + custom checks |
| Execution gate | Via router | Direct call at line 3255 |
| Fills ledger | Router-maintained | Self-managed |
| Mode enforcement | Via `TradingMode` | Via `dry_run` flag + own logic |
| Stale snapshot guard | ✅ Yes (90s) | ❌ Not present |
| Sanity check | ✅ Yes | ❌ Not present |

---

## 6. Guards Required

### 6.1 Runtime Caller Module Guard

Add to `order_router.py`:

```python
_ALLOWED_CALLER_MODULES = {
    "merid.prediction.kalshi_tools",
    "merid.prediction.trading_agent",  # for stop-loss
    "tests.",  # Allow test modules
}

_BYPASS_PATHS = {
    "merid.trading.kalshi_continuous_trader",  # Known bypass — needs migration
}

def _check_caller() -> bool:
    """Verify caller is in allowed module list."""
    import inspect
    frame = inspect.currentframe()
    try:
        # Walk up stack to find first non-router caller
        for f in inspect.getouterframes(frame):
            mod = inspect.getmodule(f.frame)
            if mod and not mod.__name__.startswith("merid.event_venues.kalshi.order_router"):
                return mod.__name__
    finally:
        del frame
    return None
```

### 6.2 CT Migration Path

**Option A:** Refactor CT to use `route_order_async()`
- Wrap CT order intent in `OrderIntent`
- Call `route_order_async()` instead of `self._post()`
- Add CT-specific source tag

**Option B:** Add CT to explicit whitelist with justification
- Document why CT needs direct access (performance, thread context)
- Add CT-specific risk checks to router for feature parity

### 6.3 Unit Test Enforcement

```python
# tests/test_order_router_caller_restrictions.py

def test_only_allowed_modules_import_router():
    """Assert only execution modules import route_order_async."""
    import ast
    import os
    
    violations = []
    for root, dirs, files in os.walk("merid"):
        for file in files:
            if file.endswith(".py"):
                path = os.path.join(root, file)
                with open(path) as f:
                    content = f.read()
                if "route_order_async" in content or "route_order" in content:
                    # Check if it's an import or call
                    tree = ast.parse(content)
                    for node in ast.walk(tree):
                        if isinstance(node, ast.ImportFrom):
                            if node.module and "order_router" in node.module:
                                module_name = path.replace("/", ".").replace("\\", ".")[:-3]
                                if module_name not in _ALLOWED_CALLERS:
                                    violations.append(module_name)
    
    assert not violations, f"Unauthorized router imports: {violations}"
```

---

## 7. Recommendations

### Immediate (P0)

1. **Document CT bypass**: Add explicit comment in `kalshi_continuous_trader.py` explaining why direct HTTP is used vs. router.

2. **Add CT to CI whitelist**: Update `.ci/venue_touchpoint_whitelist.txt` to include CT with justification comment.

### Short-term (P1)

3. **Align CT risk gates**: Add `sanity_check` and `stale_snapshot` guards to CT's pre-flight checks.

4. **Create unified risk interface**: Ensure both paths use the same `KalshiRiskManager` instance.

### Medium-term (P2)

5. **Migrate CT to router**: Refactor to use `route_order_async()` with appropriate mode handling for sync executor context.

6. **Add runtime caller guard**: ✅ Implemented — logs all caller decisions to `[AUDIT]` stream.

---

## 7. Bypass List (Technical Debt)

These modules are explicitly allowed to bypass the canonical router for documented reasons.
They are tracked as **technical debt**, not permanent architecture.

**Policy: No new bypasses allowed. Existing bypasses must be eliminated.**

| Module | Bypass Type | Current Role | Target Role | Risk Level | Migration Status |
|--------|-------------|--------------|-------------|------------|------------------|
| `kalshi_continuous_trader.py` | Direct HTTP (`self._post`) | Executor (edge + order build + HTTP) | **Strategy Driver only** (no direct HTTP) | High (skips sanity, fills, stale checks) | In Progress — Shadow Mode planned |

### CT Migration Plan: Demote from Executor to Strategy Driver

**Phase 1: Shadow Mode Adapter (Current Sprint)**
1. Create `CTExecutionAdapter` that:
   - Accepts CT's order dict
   - Converts to `OrderIntent`
   - Calls `route_order_async()` in **paper/mock mode only**
   - Logs parity diffs (HTTP result vs router result)
2. Run both paths in parallel (HTTP executes, router shadows)
3. Validate fill parity, latency, error handling equivalence

**Phase 2: Canary Flip (Next Sprint)**
1. Enable router path for 10% of CT orders (random selection)
2. Monitor for regressions via `[AUDIT]` logs and fills ledger
3. Ramp to 100% over 1 week

**Phase 3: Direct HTTP Removal (Following Sprint)**
1. Delete `self._post("/portfolio/orders")` code path
2. Remove CT from CI whitelist bypass section
3. Update classification table: CT becomes "⚠️ Signal only (no direct HTTP)"
4. Close bypass — list becomes empty

### Post-Migration CT Architecture

```
KalshiContinuousTrader (Strategy Driver)
├── Computes edge via `_compute_edge()`
├── Builds order description (ticker, side, size, price)
├── Hands off to canonical executor
│   └── Option A: TradingAgent instance
│   └── Option B: ExecutionService → router
└── NO direct HTTP — relies on executor for side effects
```

### Bypass Enforcement

1. **CI Whitelist**: All bypasses listed in `.ci/venue_touchpoint_whitelist.txt`
2. **Runtime Logs**: `[AUDIT] KNOWN_BYPASS_CALLER` entries
3. **Test Enforcement**: `test_order_router_caller_restrictions.py` validates documentation
4. **Regression Test**: Fails if second executor-like agent appears

### Prohibition on New Bypasses

**NO new executor bypasses will be accepted.** Any new strategy must:
- Feed signals into existing executor stack, OR
- Create a new executor that **also** uses `route_order_async()` (becomes additional authorized caller)

No strategy may create its own direct HTTP path to the venue.

---

## 8. Config Flags That Enable/Disable Execution

| Flag | Module | Effect |
|------|--------|--------|
| `MERID_PM_TRADING_MODE=paper` | venue_gate | Forces paper mode |
| `MERID_TRADE_MODE=paper` | trade_mode | Global mode setting |
| `KALSHI_USE_DEMO=true` | kalshi_tools | Blocks real orders |
| `KALSHI_CT_AUTO_EXIT=true` | continuous_trader | Enables sells |
| `dry_run=true` | continuous_trader | Skips actual HTTP calls |
| `LifecycleState.WARMING_UP` | trading_agent | Blocks execution |
| `execution_gate.blocked` | execution_guard | Blocks both paths |

---

## Appendix: File References

| File | Key Lines | Purpose |
|------|-----------|---------|
| `merid/event_venues/kalshi/order_router.py` | 1-1619 | Canonical order router |
| `merid/prediction/trading_agent.py` | 1366, 2055 | Agent execution calls |
| `merid/prediction/kalshi_tools.py` | 413-435 | Tool → router bridge |
| `merid/trading/kalshi_continuous_trader.py` | 3445 | **Direct HTTP call** |
| `merid/trading/kalshi_continuous_trader.py` | 3255-3277 | CT risk gate |
| `.ci/venue_touchpoint_whitelist.txt` | 14-21 | Current whitelist |
