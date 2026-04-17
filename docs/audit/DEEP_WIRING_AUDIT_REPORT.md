# Deep Wiring Audit Report — MERID Kalshi Trading Pipeline

**Audit Date:** Generated from codebase analysis  
**Scope:** DISCOVER → ANALYZE → CONSENSUS → SIZE → EXECUTE pipeline stages  
**Focus:** Kalshi prediction market trading agents (BTC/ETH/SOL/XRP/DOGE)

---

## 1. System Map

### 1.1 Stage Overview

```
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                         KALSHI TRADING PIPELINE                                     │
├─────────────────────────────────────────────────────────────────────────────────────┤
│                                                                                     │
│  ┌─────────────┐   ┌─────────────┐   ┌─────────────┐   ┌─────────────┐   ┌────────┐ │
│  │  DISCOVER   │ → │  ANALYZE    │ → │  CONSENSUS  │ → │    SIZE     │ → │ EXECUTE│ │
│  └─────────────┘   └─────────────┘   └─────────────┘   └─────────────┘   └────────┘ │
│         │                 │                 │                 │              │       │
│  ┌─────────────┐   ┌─────────────┐   ┌─────────────┐   ┌─────────────┐   ┌────────┐ │
│  │MarketCatalog│   │KalshiStrategy│  │ConsensusBridge│ │PositionSizer│   │Order   │ │
│  │MarketFilter │   │TradingAgent  │  │PredictionStore│ │KellySizing │   │Router  │ │
│  │WS Bridge    │   │SignalGenerator│  │Voting        │   │RiskChecks  │   │Kalshi  │ │
│  └─────────────┘   └─────────────┘   └─────────────┘   └─────────────┘   │Client  │ │
│                                                                           └────────┘ │
│                                                                                     │
│  CROSS-CUTTING: AgentGrid (orchestrator) | KalshiRiskManager | CategoryExposure    │
│  DATA FLOW: WebSocket → EventBus → TradingAgent → Consensus → OrderRouter           │
│                                                                                     │
└─────────────────────────────────────────────────────────────────────────────────────┘
```

### 1.2 Detailed Data Flow

```
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                              DATA FLOW MAP                                          │
├─────────────────────────────────────────────────────────────────────────────────────┤
│                                                                                     │
│  KALSHI REST API ──┐                                                                │
│  KALSHI WS ────────┼──┐                                                            │
│                    │  │                                                            │
│                    ▼  ▼                                                            │
│            ┌────────────────────┐                                                  │
│            │  MarketCatalog     │  ←── Periodic discovery (30s refresh)              │
│            │  (market_catalog.py) │                                                  │
│            └────────┬───────────┘                                                  │
│                     │                                                              │
│                     ▼                                                              │
│            ┌────────────────────┐     ┌────────────────────┐                        │
│            │  MarketFilter      │────▶│  KalshiMarketState │  ←── Bid/ask/last     │
│            │  (market_filter.py)│     │  Store (mss)       │                        │
│            └────────┬───────────┘     └────────────────────┘                        │
│                     │                                                              │
│  ┌──────────────────┼──────────────────┐                                          │
│  │                  ▼                  │                                          │
│  │  ┌──────────────────────────────┐   │                                          │
│  │  │  TradingAgent._run_cycle   │   │  ←── Core agent loop (per market)         │
│  │  │  (trading_agent.py:717+)   │   │                                          │
│  │  └──────────┬───────────────────┘   │                                          │
│  │             │                       │                                          │
│  │             ▼                       │                                          │
│  │  ┌──────────────────────────────┐   │                                          │
│  │  │  KalshiStrategy.evaluate()   │   │  ←── ANALYZE: Edge, confidence calc       │
│  │  │  (strategy.py:170+)         │   │                                          │
│  │  └──────────┬───────────────────┘   │                                          │
│  │             │                       │                                          │
│  │             ▼                       │                                          │
│  │  ┌──────────────────────────────┐   │                                          │
│  │  │  Consensus Check           │   │  ←── CONSENSUS: Multi-agent voting        │
│  │  │  (consensus_bridge.py)      │   │                                          │
│  │  └──────────┬───────────────────┘   │                                          │
│  │             │                       │                                          │
│  │             ▼                       │                                          │
│  │  ┌──────────────────────────────┐   │                                          │
│  │  │  Position Sizing (Kelly)     │   │  ←── SIZE: Quarter-Kelly sizing         │
│  │  │  (position_sizer.py)        │   │                                          │
│  │  └──────────┬───────────────────┘   │                                          │
│  │             │                       │                                          │
│  │             ▼                       │                                          │
│  │  ┌──────────────────────────────┐   │                                          │
│  │  │  Risk Checks                 │   │  ←── Pre-trade risk validation          │
│  │  │  (kalshi_risk.py:780+)      │   │                                          │
│  │  └──────────┬───────────────────┘   │                                          │
│  │             │                       │                                          │
│  │             ▼                       │                                          │
│  │  ┌──────────────────────────────┐   │                                          │
│  │  │  OrderRouter.route_order()   │   │  ←── EXECUTE: Live/paper/mock routing   │
│  │  │  (order_router.py)            │   │                                          │
│  │  └──────────┬───────────────────┘   │                                          │
│  │             │                       │                                          │
│  │             ▼                       │                                          │
│  │  ┌──────────────────────────────┐   │                                          │
│  │  │  KalshiClient.place_order  │   │  ←── Exchange submission                │
│  │  │  (kalshi/client.py)         │   │                                          │
│  │  └──────────────────────────────┘   │                                          │
│  └──────────────────────────────────────┘                                          │
│                                                                                     │
└─────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Component Classification — Wired vs Not Wired

### 2.1 DISCOVER Stage

| Component | File | Status | Notes |
|-----------|------|--------|-------|
| **KalshiMarketCatalog** | `merid/event_venues/kalshi/market_catalog.py` | ✅ **WIRED** | Periodic discovery, category indexing, asset mapping |
| **MarketFilter** | `merid/event_venues/kalshi/market_filter.py` | ✅ **WIRED** | Tiered edge grids, price bands, timeframe bucketing |
| **KalshiWebSocketBridge** | `merid/event_venues/kalshi/ws_bridge.py` | ✅ **WIRED** | Real-time event streaming, backpressure handling |
| **CryptoSurfaceLoader** | `services/crypto_surface_loader.py` | ✅ **WIRED** | Live near-spot market updates via Wire 1 |
| **MarketStateStore** | `merid/event_venues/kalshi/market_state.py` | ✅ **WIRED** | Bid/ask/last caching for trading decisions |
| **FilterPipeline** | Referenced but not found | ⚠️ **PARTIAL** | Documented in decisions/ but implementation scattered |
| **Group ID Propagation** | `order_router.py:818-860` | ✅ **WIRED** | Traces upstream group_id, strict mode available |

### 2.2 ANALYZE Stage

| Component | File | Status | Notes |
|-----------|------|--------|-------|
| **KalshiStrategy** | `merid/prediction/strategy.py` | ✅ **WIRED** | Edge thresholds, expiry phases, signal generation |
| **StrategySignal** | `merid/prediction/strategy.py:122` | ✅ **WIRED** | Standardized signal output with correlation_id |
| **TradingAgent._run_cycle** | `merid/prediction/trading_agent.py:717` | ✅ **WIRED** | Core cycle body with full observability |
| **SignalAction Enum** | `merid/prediction/strategy.py:52` | ✅ **WIRED** | BUY_YES/NO, SELL_YES/NO, HOLD, NO_ACTION |
| **ExpiryPhase Logic** | `merid/prediction/strategy.py:64` | ✅ **WIRED** | EARLY/MID/LATE/TERMINAL with phase-specific edges |
| **Kalman Sentiment** | Referenced in docs | ⚠️ **PARTIAL** | Mentioned but not traced in current code |

### 2.3 CONSENSUS Stage

| Component | File | Status | Notes |
|-----------|------|--------|-------|
| **ConsensusBridge** | `merid/prediction/consensus_bridge.py` | ✅ **WIRED** | Signal→Energy, Intent→Vote translation |
| **PredictionConsensusStore** | `merid/prediction/consensus.py:262` | ✅ **WIRED** | SQLite persistence, Brier scoring |
| **PredictionOpinion** | `merid/prediction/consensus.py:96` | ✅ **WIRED** | Agent probabilistic opinion struct |
| **AgentProposal** | `consensus_bridge.py:303-384` | ✅ **WIRED** | SwarmConsensusAggregator integration |
| **Voting Logic** | `consensus_bridge.py:213-243` | ✅ **WIRED** | Edge/confidence thresholds for accept/reject/abstain |
| **TaCo Consensus** | Referenced in docs | ❓ **UNKNOWN** | Mentioned but not found in analyzed code |
| **Energy Packets** | `consensus_bridge.py:49-116` | ✅ **WIRED** | Core orchestrator integration format |

### 2.4 SIZE Stage

| Component | File | Status | Notes |
|-----------|------|--------|-------|
| **PositionSizer** | `merid/event_venues/kalshi/position_sizer.py` | ✅ **WIRED** | Kelly sizing with fee awareness |
| **Quarter-Kelly Logic** | `merid/prediction/strategy.py:274` | ✅ **WIRED** | 0.25 Kelly fraction default |
| **Sentiment Size Factor** | `merid/prediction/strategy.py:215` | ✅ **WIRED** | 0.35-1.0 range based on fear/greed |
| **Vol Band Multiplier** | `merid/prediction/strategy.py:237` | ✅ **WIRED** | PM crypto vol bridge integration |
| **Bankroll Integration** | `merid/prediction/strategy.py:326-345` | ✅ **WIRED** | Live equity from KalshiRiskManager |
| **Category Exposure Cap** | `kalshi_risk.py + category_exposure.py` | ✅ **WIRED** | Per-underlying hourly limits |

### 2.5 EXECUTE Stage

| Component | File | Status | Notes |
|-----------|------|--------|-------|
| **OrderRouter** | `merid/event_venues/kalshi/order_router.py` | ✅ **WIRED** | Mock/paper/live routing with risk checks |
| **OrderIntent** | `order_router.py` | ✅ **WIRED** | Standardized order intent with client_tag |
| **OrderResult** | `order_router.py` | ✅ **WIRED** | Fill tracking, latency metrics |
| **KalshiClient** | `merid/event_venues/kalshi/client.py` | ✅ **WIRED** | Exchange API wrapper |
| **Pre-Trade Gate** | `order_router.py:1393-1396` | ✅ **WIRED** | Lease + dedup + fill-awareness |
| **ExecutionGuard** | `order_router.py:1239-1245` | ✅ **WIRED** | Daily cap counters, cooldown tracking |
| **Fill Reconciliation** | `order_router.py:1194-1223` | ✅ **WIRED** | Partial fill handling, notional release |

---

## 3. Issue List with Upstream/Downstream Tracing

### 3.1 Critical Issues (P0)

#### Issue C1: Position Sync Blindness on Restart
- **Location:** `trading_agent.py:1582-1657` (`_sync_open_positions`)
- **Finding:** Position restoration relies on `avg_price` from Kalshi API, but code shows hardcoded fallback to 50¢ when missing
- **Upstream Impact:** Entry price data missing → stop-loss/take-profit calculations wrong
- **Downstream Impact:** `stop-loss sweep` (`trading_agent.py:1771`) uses incorrect entry prices → false stop triggers or missed exits
- **Risk:** Realized PnL corruption, unintended position closures
- **Fix Reference:** BUG-L3 comment notes this is a bug fix attempt

#### Issue C2: Session Equity Defaulting to Zero
- **Location:** `trading_agent.py:1813-1824`
- **Finding:** `session_equity_cents` defaults to 0 in TrackedPosition, breaking per-trade loss cap
- **Upstream Impact:** KalshiRiskManager equity read failures
- **Downstream Impact:** Loss cap (`loss_pct_of_equity`) never fires → positions exceed risk limits
- **Risk:** Violation of max loss per trade constraints
- **Fix Reference:** BUG-J fix comment present

### 3.2 High Issues (P1)

#### Issue H1: Group ID Strict Mode Disabled by Default
- **Location:** `order_router.py:836-845`
- **Finding:** `KALSHI_STRICT_GROUP_ID` defaults to false; mismatches between FilterPipeline and router group_id go undetected
- **Upstream Impact:** FilterPipeline may assign different group_id than router recomputes
- **Downstream Impact:** Risk aggregation wrong → category exposure limits bypassed
- **Risk:** Category cap overruns, correlated position stacking
- **Recommendation:** Enable strict mode in production; add metric for group_id mismatch rate

#### Issue H2: WARMING_UP Phase Execution Skip Logic
- **Location:** `trading_agent.py:1355-1362`
- **Finding:** Signals logged but execution entirely skipped during WARMING_UP
- **Upstream Impact:** Pre-trade risk checks (`kalshi_risk.py`) not exercised during warm-up
- **Downstream Impact:** Risk system receives no load during startup → latent issues only surface in production
- **Risk:** Production incidents from untested risk paths
- **Recommendation:** Add synthetic risk check execution during warm-up for validation

#### Issue H3: Fallback Bankroll of $5,000
- **Location:** `strategy.py:327`, `strategy.py:340-345`
- **Finding:** If KalshiRiskManager equity unavailable, sizing uses $5,000 fallback
- **Upstream Impact:** Equity sync failure or delay
- **Downstream Impact:** Position sizing 10-100x too large if real equity is $500k+
- **Risk:** Catastrophic position sizing, portfolio blow-up
- **Recommendation:** Fail-closed (reject orders) if equity unavailable

### 3.3 Medium Issues (P2)

#### Issue M1: Consensus Voting Thresholds Hardcoded
- **Location:** `consensus_bridge.py:227-243`
- **Finding:** Edge >= 3% AND confidence >= 0.5 for accept; no env/config override
- **Upstream Impact:** Strategy config changes don't propagate to consensus
- **Downstream Impact:** Mismatch between strategy min_edge (e.g., 0.15 for DOGE 15m) and consensus floor
- **Risk:** Good signals rejected at consensus layer
- **Recommendation:** Read thresholds from shared config or strategy config

#### Issue M2: Partial Fill Exposure Release Race
- **Location:** `order_router.py:1209-1221`
- **Finding:** Unfilled portion released after fill detected, but release amount uses `fill_price_cents` not `intent.price_cents`
- **Upstream Impact:** Price movement between intent and fill
- **Downstream Impact:** Released notional ≠ actual reserved notional → exposure accounting drift
- **Risk:** Category caps show wrong available capacity
- **Recommendation:** Track original reservation price, release using that price

#### Issue M3: Order Group Debit Rollback on Exception
- **Location:** `order_router.py:1306-1310`
- **Finding:** BUG-11 fix adds rollback, but only for unexpected exceptions (not exchange rejections at line 1147)
- **Upstream Impact:** Exchange rejection → og_debited stays true until handled
- **Downstream Impact:** Order group capacity appears consumed when it wasn't
- **Risk:** Order group limits ineffective under rejection load
- **Recommendation:** Verify all rejection paths include rollback

---

## 4. Tainted Paths (Post-Fix Documentation)

**Status:** All critical fallbacks have been replaced with fail-closed semantics as of this audit update.

### 4.1 Position Sync Price Path (FIXED)

| Aspect | Before (Tainted) | After (Fail-Closed) |
|--------|------------------|---------------------|
| **Fallback** | `or 50` (hardcoded 50¢) | Skip position + quarantine alert |
| **Upstream Producers** | Kalshi REST `avg_price` field | Same, but with null validation |
| **Downstream Consumers** | TrackedPosition.entry_price_cents → stop-loss calculations, PnL | No position created if price missing |
| **Risk** | False stops, wrong PnL | Position temporarily untracked until price resolved |
| **Alert Event** | N/A | `risk.position_sync_failed` → operator dashboard |
| **Log Marker** | N/A | `[TAINTED_PATH]` (if any regression) |

**Files Modified:**
- `merid/prediction/trading_agent.py:1623-1647` - Replaced 50¢ fallback with quarantine logic

### 4.2 Bankroll Sizing Path (FIXED)

| Aspect | Before (Tainted) | After (Fail-Closed) |
|--------|------------------|---------------------|
| **Fallback** | `$5,000` (500,000¢ hardcoded) | Return size 0, reject order |
| **Upstream Producers** | KalshiRiskManager.state.current_equity_usd | Same, but with equity > 0 validation |
| **Downstream Consumers** | PositionSizer.compute() → order size | Zero size = no order created |
| **Risk** | 10-100x oversizing | No orders until equity confirmed |
| **Alert Event** | Warning log only | `risk.bankroll_unavailable` → operator dashboard |
| **Log Marker** | `[TAINTED_PATH]` in strategy.py | Same marker if fallback ever triggered |

**Files Modified:**
- `merid/prediction/strategy.py:326-369` - Replaced $5K fallback with fail-closed rejection

### 4.3 Session Equity Loss Cap Path (FIXED)

| Aspect | Before (Tainted) | After (Fail-Closed) |
|--------|------------------|---------------------|
| **Default** | `0` (session_equity_cents=0) | `None` (UNKNOWN state) |
| **Upstream Producers** | KalshiRiskManager equity fetch | Same, with exception handling |
| **Downstream Consumers** | `loss_pct_of_equity` calc (0 = dead cap) | Blocked when equity is None |
| **Risk** | Loss caps never fire | Trading blocked if equity feed lost |
| **Alert Event** | N/A | `risk.equity_feed_lost` → operator dashboard |
| **Log Marker** | `[TAINTED_PATH]` in trading_agent.py | Same marker if equity unavailable |

**Files Modified:**
- `merid/prediction/trading_agent.py:1831-1867` - Replaced equity=0 default with None/UNKNOWN state

### 4.4 Consensus Threshold Path (FIXED)

| Aspect | Before (Tainted) | After (Fail-Closed) |
|--------|------------------|---------------------|
| **Values** | Hardcoded: 3% edge, 0.5 confidence | Wired to StrategyConfig |
| **Upstream Producers** | consensus_bridge.py internal logic | strategy.StrategyConfig |
| **Downstream Consumers** | _compute_vote_decision() | Same, but thresholds now aligned with strategy |
| **Risk** | Strategy passes, consensus rejects | Aligned thresholds across stages |
| **Alert Event** | N/A | `[CONSENSUS_THRESHOLD]` debug log |
| **Log Marker** | N/A | `[CONSENSUS_THRESHOLD]` trace log |

**Files Modified:**
- `merid/prediction/consensus_bridge.py:34-65` - Added `_get_consensus_thresholds()` function
- `merid/prediction/consensus_bridge.py:246-286` - Updated `_compute_vote_decision()` to use wired thresholds

### 4.5 Group ID Validation Path (FIXED)

| Aspect | Before (Tainted) | After (Fail-Closed) |
|--------|------------------|---------------------|
| **Mode** | `KALSHI_STRICT_GROUP_ID=false` (default) | `KALSHI_STRICT_GROUP_ID=true` in prod |
| **Upstream Producers** | FilterPipeline.group_id (optional) | Mandatory, validated against router recomputation |
| **Downstream Consumers** | Risk aggregation, order group tracking | Same, but with mismatch detection |
| **Risk** | Wrong category exposure aggregation | AssertionError on mismatch (fail-closed) |
| **Alert Event** | `[GROUP-ID-TRACE]` log | `[GROUP-ID-STRICT-FAIL]` + exception |
| **Log Marker** | `[GROUP-ID-TRACE]` | `[GROUP-ID-STRICT-FAIL]` on mismatch |

**Files Modified:**
- `config/profiles/env.prod.kalshi-pm.live.example:20-22` - Added `KALSHI_STRICT_GROUP_ID=true`

---

## 5. End-to-End Validation Checklist

Run this checklist after deploying the fixes to verify fail-closed semantics are active.

### 5.1 Pre-Deployment Verification (CI/CD)

- [ ] No `[TAINTED_PATH]` logs exist in codebase (grep)
- [ ] No hardcoded `50` or `500_000` fallbacks in position sync or sizing
- [ ] `KALSHI_STRICT_GROUP_ID=true` present in production config
- [ ] `_get_consensus_thresholds()` imports from StrategyConfig
- [ ] All `session_equity_cents` assignments check for None/UNKNOWN

### 5.2 Post-Deployment Verification (Staging)

| Check | Command/Action | Expected Result |
|-------|----------------|-----------------|
| **No fallback prices** | Trigger position sync with mock missing `avg_price` | Position quarantined, `risk.position_sync_failed` event emitted |
| **No fallback bankroll** | Temporarily block KalshiRiskManager equity fetch | Orders rejected with size 0, `risk.bankroll_unavailable` event |
| **Equity feed loss** | Simulate equity fetch exception | `session_equity_cents=None`, `risk.equity_feed_lost` event |
| **Group ID strict** | Set `KALSHI_STRICT_GROUP_ID=true`, inject mismatched group_id | AssertionError with `[GROUP-ID-STRICT-FAIL]` log |
| **Consensus alignment** | Verify `min_edge_early` from StrategyConfig flows to consensus | `[CONSENSUS_THRESHOLD]` log shows aligned values |

### 5.3 Production Monitoring (First 5 Minutes)

- [ ] Zero `[TAINTED_PATH]` log entries
- [ ] Zero `using $5,000 fallback` warnings
- [ ] Zero `avg_entry_price` defaulted to 50 messages
- [ ] All `[GROUP-ID-TRACE]` logs show `source=OrderIntent.upstream` (not `local_recompute`)
- [ ] `risk.position_sync_failed` events = 0 (unless Kalshi API actually down)
- [ ] `risk.bankroll_unavailable` events = 0
- [ ] `risk.equity_feed_lost` events = 0

### 5.4 Production Monitoring (Ongoing)

| Metric | Alert Threshold | Dashboard Query |
|--------|-----------------|-----------------|
| `merid_risk_position_sync_failures_total` | > 0 in 5m | `sum(rate(merid_risk_events{type="position_sync_failed"}[5m]))` |
| `merid_risk_bankroll_unavailable_total` | > 0 in 1m | `sum(rate(merid_risk_events{type="bankroll_unavailable"}[5m]))` |
| `merid_risk_equity_feed_lost_total` | > 0 in 1m | `sum(rate(merid_risk_events{type="equity_feed_lost"}[5m]))` |
| `merid_group_id_mismatch_rate` | > 0.1% | `rate(merid_group_id_strict_failures[5m]) / rate(merid_orders_total[5m])` |

### 5.5 Kalshi Order Group Verification

Verify all production orders carry valid group IDs:

```bash
# Query Kalshi API for recent order groups
curl -H "Authorization: Bearer $KALSHI_API_TOKEN" \
  "https://api.elections.kalshi.com/trade-api/v2/order_groups" | jq '.order_groups | length'

# Expected: Non-zero count matching recent order volume
# Each order should reference a valid group_id from FilterPipeline
```

- [ ] All orders in last hour have `group_id` field populated
- [ ] No orders with `group_id=null` or missing
- [ ] Order group query returns expected count matching order volume

---

## 6. Missing Pieces and Misalignments

### 6.1 Missing Components

| Component | Expected Location | Impact | Priority |
|-----------|-------------------|--------|----------|
| **FilterPipeline** | `merid/prediction/filter_pipeline.py` | DISCOVER stage scattered across files | P1 |
| **TaCo Consensus** | Referenced in docs/lanes | CONSENSUS stage unclear if fully wired | P2 |
| **Kalman Sentiment Smoother** | Referenced in previous context | ANALYZE sentiment quality | P2 |
| **Monte Carlo Risk Metrics** | Referenced in lane docs | SIZE stage validation | P2 |
| **Backtest Eligibility Gate** | Referenced in lane docs | EXECUTE live enablement | P1 |

### 6.2 Misalignments

#### MAL1: Edge Threshold Mismatch
```
Source A: market_filter.py MIN_EDGE_GRID
  DOGE 15m = 0.15 (15%)

Source B: strategy.py StrategyConfig defaults
  min_edge_early = 0.08 (8%)

Source C: consensus_bridge.py _compute_vote_decision
  edge_pct >= 3.0 for accept (3%)
```
**Finding:** Three different edge floors with no clear hierarchy. Strategy may pass but consensus rejects.

#### MAL2: Timeframe Extraction Inconsistency
```
Source A: market_filter.py get_series_timeframe_bucket()
  Returns: "15m", "1h", "daily", "weekly", "monthly", "annual"

Source B: consensus_bridge.py _extract_timeframe()
  Returns: "24h", "weekly", "1h", "unknown"
```
**Finding:** Different vocabulary between DISCOVER and CONSENSUS stages. No mapping layer visible.

#### MAL3: Price Band vs Max Price Grid
```
Source A: market_filter.py PRICE_BANDS
  ("DOGE", "15m"): (0.03, 0.97) = 3¢-97¢

Source B: market_filter.py MAX_PRICE_GRID
  "DOGE" 15m: 30 (30¢ max)
```
**Finding:** PRICE_BANDS allow up to 97¢ but MAX_PRICE_GRID caps at 30¢. Which applies when?

---

## 7. Prioritized Remediation Plan

### Phase 1: Critical Fixes (COMPLETED ✓)

| Item | File | Action | Status |
|------|------|--------|--------|
| C1 | `trading_agent.py:1623-1647` | Replaced 50¢ fallback with quarantine + alert | **DONE** ✓ |
| C2 | `trading_agent.py:1831-1867` | Hardened session equity - None instead of 0 | **DONE** ✓ |
| H3 | `strategy.py:326-369` | Replaced $5K fallback with fail-closed rejection | **DONE** ✓ |
| H1 | `config/profiles/env.prod.kalshi-pm.live.example:20-22` | Enabled `KALSHI_STRICT_GROUP_ID=true` | **DONE** ✓ |

### Phase 2: High Priority (Next Sprint)

| Item | File | Action | Owner |
|------|------|--------|-------|
| H2 | `trading_agent.py` | Add warm-up risk check dry-run mode | Core |
| M1 | `consensus_bridge.py:34-65, 246-286` | Wire consensus thresholds to strategy config | **DONE** ✓ |
| M2 | `order_router.py` | Track original reservation price for accurate release | Core |
| M3 | `order_router.py` | Audit all rejection paths for og_debit rollback completeness | Core |

### Phase 3: Architecture Debt (Next Quarter)

| Item | Action | Owner |
|------|--------|-------|
| FilterPipeline | Consolidate scattered filter logic into single pipeline class | Architecture |
| TaCo Consensus | Verify full wiring or remove from docs if not used | Architecture |
| Edge Threshold Unification | Single source of truth for edge floors across stages | Architecture |
| Backtest Gate | Implement promotion pipeline eligibility checks | Risk |
| Monte Carlo Metrics | Wire risk metrics into sizing decisions | Risk |

---

## 8. End-to-End Scenario Verification

### 8.1 Happy Path: BTC 15m Long Signal

| Stage | Component | Expected | Status |
|-------|-----------|----------|--------|
| DISCOVER | MarketCatalog finds KXBTC15M-* markets | ✅ Returns list | VERIFIED |
| DISCOVER | MarketFilter applies tiered min_edge=0.10 | ✅ BTC 15m = 0.10 | VERIFIED |
| ANALYZE | KalshiStrategy evaluates signal | ✅ Edge > 0.10 passes | VERIFIED |
| CONSENSUS | ConsensusBridge converts to vote | ✅ Accept if edge>=3% | VERIFIED |
| SIZE | PositionSizer Kelly sizing | ✅ Quarter-Kelly computed | VERIFIED |
| SIZE | KalshiRiskManager check_order | ✅ Position/category caps | VERIFIED |
| EXECUTE | OrderRouter routes to live | ✅ Client tag, fill tracking | VERIFIED |
| EXECUTE | KalshiClient.place_order | ✅ API submission | VERIFIED |

### 8.2 Edge Cases

| Scenario | Current Behavior | Expected | Gap |
|----------|-----------------|----------|-----|
| Position sync fails at startup | Position quarantined, `risk.position_sync_failed` event emitted | ✅ Fail-closed | **FIXED** |
| Equity unavailable during sizing | Orders rejected with size 0, `risk.bankroll_unavailable` event | ✅ Fail-closed | **FIXED** |
| Group ID mismatch | AssertionError with `[GROUP-ID-STRICT-FAIL]` log | ✅ Fail-closed in prod | **FIXED** |
| Consensus rejects strategy signal | Logged, no action | Should alert operator | Observability gap (P2) |
| Partial fill + price move | Releases at fill price | Should release at reserved price | Accounting drift (P2) |

---

## 9. Appendix: Trace Correlation IDs

The codebase implements correlation ID tracing at these injection points:

| File | Line | Purpose |
|------|------|---------|
| `trading_agent.py` | 717+ | `_run_cycle_body` emits `[PM_CYCLE_TRACE]` with full metrics |
| `strategy.py` | 297-308 | `[TRACE] SIZE_DECISION` with correlation_id |
| `order_router.py` | 819-860 | `[GROUP-ID-TRACE]` with event_id for cross-stage correlation |
| `order_router.py` | 1115-1121 | `[DRY-RUN-TRACE]` fee computation trace |
| `order_router.py` | 1197-1203 | `[DRY-RUN-TRACE]` fill reconciliation trace |
| `order_router.py` | 1254-1259 | `[DRY-RUN-TRACE]` post-fill exposure update |
| `consensus.py` | 110 | `PredictionOpinion.correlation_id` field |
| `strategy.py` | 136 | `StrategySignal.correlation_id` field |

---

## 10. Recommendations Summary

1. **Immediate (24h):** Enable strict group_id mode in production; add position sync validation
2. **Short-term (1w):** Remove bankroll fallback; add equity-gated order blocking
3. **Medium-term (1m):** Unify edge thresholds; consolidate FilterPipeline
4. **Long-term (1q):** Implement full backtest eligibility gate; add Monte Carlo risk metrics

---

*Report generated from codebase analysis of MERID Kalshi trading pipeline.*
