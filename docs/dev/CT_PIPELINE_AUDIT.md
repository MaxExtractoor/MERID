# Kalshi Continuous Trader — End-to-End Pipeline Audit

**Date**: 2026-03-28  
**Scope**: Full trace of `KalshiContinuousTrader._run_cycle_inner()` from data ingestion to order submission.  
**Goal**: Identify where `max_strike_distance_pct` lives today, map all filter/gate layers, and surface blockers for the planned refactor (move tiered strike-distance into `KalshiRiskConfig`).

---

## 1. Lifecycle Diagram

```
┌──────────────────────────────────────────────────────────────────────┐
│  KalshiContinuousTrader.run()  (async loop, thread-executor)        │
│                                                                      │
│  ┌────────────────────────────────────────────────────────────────┐  │
│  │  _run_cycle_inner()  — one synchronous trading cycle           │  │
│  │                                                                │  │
│  │  ┌─────────────────────────────────────────────────────────┐   │  │
│  │  │ GATE LAYER 1: execution_gate (core/execution_gate.py)   │   │  │
│  │  │  → blocked / limited / clear                            │   │  │
│  │  │  → limited = reduce-only (exits OK, no new entries)     │   │  │
│  │  └─────────────────────────────────────────────────────────┘   │  │
│  │                          ↓                                     │  │
│  │  ┌─────────────────────────────────────────────────────────┐   │  │
│  │  │ GATE LAYER 2: risk_controller.can_trade()               │   │  │
│  │  │ GATE LAYER 3: KalshiRiskManager.kill_switch_active      │   │  │
│  │  └─────────────────────────────────────────────────────────┘   │  │
│  │                          ↓                                     │  │
│  │  ┌─────────────────────────────────────────────────────────┐   │  │
│  │  │ UPSTREAM: Spot Prices                                   │   │  │
│  │  │  → CryptoSpotService (Coinbase → BinanceUS → CoinGecko) │   │  │
│  │  │  → Per-asset: BTC, ETH, SOL, XRP, DOGE                 │   │  │
│  │  │  → Staleness check + degraded-feed guard                │   │  │
│  │  └─────────────────────────────────────────────────────────┘   │  │
│  │                          ↓                                     │  │
│  │  ┌─────────────────────────────────────────────────────────┐   │  │
│  │  │ UPSTREAM: Indicator Stacks                              │   │  │
│  │  │  → crypto_15m_indicators.py per asset                   │   │  │
│  │  │  → EMA(50) trend, RSI(8), MACD(8,21,5), ATR(14)       │   │  │
│  │  │  → Feeds: bias, confidence, vol band                    │   │  │
│  │  └─────────────────────────────────────────────────────────┘   │  │
│  │                          ↓                                     │  │
│  │  ┌─────────────────────────────────────────────────────────┐   │  │
│  │  │ BANKROLL UPDATE                                         │   │  │
│  │  │  → _get_balance() → balance_cents + portfolio_cents     │   │  │
│  │  │  → bankroll.update_balance() + drawdown check           │   │  │
│  │  │  → vol benchmark from spot → vol band → fee window      │   │  │
│  │  └─────────────────────────────────────────────────────────┘   │  │
│  │                          ↓                                     │  │
│  │  ┌─────────────────────────────────────────────────────────┐   │  │
│  │  │ POSITIONS + EXITS                                       │   │  │
│  │  │  → _get_positions() (REST /portfolio/positions)         │   │  │
│  │  │  → profit-take / stop-loss evaluation per position      │   │  │
│  │  │  → auto-exit via REST sell (if KALSHI_CT_AUTO_EXIT)     │   │  │
│  │  └─────────────────────────────────────────────────────────┘   │  │
│  │                          ↓                                     │  │
│  │  ┌─────────────────────────────────────────────────────────┐   │  │
│  │  │ MARKET FETCH                                            │   │  │
│  │  │  → Per series ticker in _asset_series_map               │   │  │
│  │  │  → GET /markets?series_ticker={s}&status=open           │   │  │
│  │  │  → Grouped by asset → Dict[str, List[Dict]]            │   │  │
│  │  └─────────────────────────────────────────────────────────┘   │  │
│  │                          ↓                                     │  │
│  │  ╔═════════════════════════════════════════════════════════╗   │  │
│  │  ║ FILTER STAGE 1: FilterPipeline                         ║   │  │
│  │  ║  (kalshi_filter_pipeline.py)                           ║   │  │
│  │  ║  → Liquidity: min_volume, min_OI, max_spread           ║   │  │
│  │  ║  → Expiry: min/max minutes, RTI quarantine             ║   │  │
│  │  ║  → CFB quarantine (adapter != live)                    ║   │  │
│  │  ║  → Strike parse: threshold/bracket vs directional      ║   │  │
│  │  ║  → Distance filter: DISABLED (set to 100% no-op)      ║   │  │
│  │  ║  → Per-asset + global candidate cap                    ║   │  │
│  │  ║  → Output: List[MarketCandidate] with group_id         ║   │  │
│  │  ╚═════════════════════════════════════════════════════════╝   │  │
│  │                          ↓                                     │  │
│  │  ╔═════════════════════════════════════════════════════════╗   │  │
│  │  ║ FILTER STAGE 2: NearSpotSelector                       ║   │  │
│  │  ║  (market_filter.py → select_near_spot_best_edge)       ║   │  │
│  │  ║                                                        ║   │  │
│  │  ║  ★ max_distance_pct = config.max_strike_distance_pct  ║   │  │
│  │  ║    (FLAT 12.5% from TraderConfig — NOT tiered)         ║   │  │
│  │  ║                                                        ║   │  │
│  │  ║  → use_tiered_min_edge=True  (MIN_EDGE_GRID)          ║   │  │
│  │  ║  → use_tiered_max_price=True (MAX_PRICE_GRID)         ║   │  │
│  │  ║  → Bucket by (asset, timeframe, direction)             ║   │  │
│  │  ║  → Sort: closest-to-spot, then best-edge               ║   │  │
│  │  ║  → Take top 2 per bucket                               ║   │  │
│  │  ╚═════════════════════════════════════════════════════════╝   │  │
│  │                          ↓                                     │  │
│  │  ┌─────────────────────────────────────────────────────────┐   │  │
│  │  │ OVERLAP GROUPING                                        │   │  │
│  │  │  → MarketFilter.group_overlapping()                     │   │  │
│  │  │  → Same underlying + expiry within overlap_window       │   │  │
│  │  │  → Pick best edge per overlap group                     │   │  │
│  │  └─────────────────────────────────────────────────────────┘   │  │
│  │                          ↓                                     │  │
│  │  ┌─────────────────────────────────────────────────────────┐   │  │
│  │  │ EDGE COMPUTATION: _compute_edge()                       │   │  │
│  │  │  → Directional: indicator stack bias ± 15% tilt         │   │  │
│  │  │  → Threshold: vol-aware logistic (dist_pct / σ√t)      │   │  │
│  │  │  → Fee-aware edge = |model_prob - implied| - fee - slip │   │  │
│  │  │  → Orderbook enrichment (yes/no bid/ask)                │   │  │
│  │  │  → Stale indicator guard → edge = -1 (kills entry)      │   │  │
│  │  └─────────────────────────────────────────────────────────┘   │  │
│  │                          ↓                                     │  │
│  │  ┌─────────────────────────────────────────────────────────┐   │  │
│  │  │ GATE LAYER 4: allow_new_entries check                   │   │  │
│  │  │  → If execution_gate "limited" → tradeable = []         │   │  │
│  │  │ GATE LAYER 5: spot_feed_degraded → tradeable = []       │   │  │
│  │  │ GATE LAYER 6: _live_api_orders_allowed()                │   │  │
│  │  │  → dry_run=True: always OK                              │   │  │
│  │  │  → KALSHI_ENV != live: always OK                        │   │  │
│  │  │  → KALSHI_CT_BYPASS_PM_LIVE_GATE: override              │   │  │
│  │  │  → else: requires MERID_PM_TRADING_MODE=live            │   │  │
│  │  └─────────────────────────────────────────────────────────┘   │  │
│  │                          ↓                                     │  │
│  │  ┌─────────────────────────────────────────────────────────┐   │  │
│  │  │ SIZING: BankrollManager.calculate_order_size()          │   │  │
│  │  │  (= KalshiRiskEngine)                                   │   │  │
│  │  │  → Halt check, min balance, max position, max open      │   │  │
│  │  │  → Fee-aware min_edge (midcurve/penny multipliers)      │   │  │
│  │  │  → Fractional Kelly with max_risk cap                   │   │  │
│  │  │  → Anti-churn hysteresis                                │   │  │
│  │  │  → Total exposure cap                                   │   │  │
│  │  └─────────────────────────────────────────────────────────┘   │  │
│  │                          ↓                                     │  │
│  │  ┌─────────────────────────────────────────────────────────┐   │  │
│  │  │ EXPOSURE GATES                                          │   │  │
│  │  │  → evaluate_entry_exposure_skip():                      │   │  │
│  │  │    Stage 1: per-asset cap (asset_max_exposure_pct ×     │   │  │
│  │  │             series_exposure_multiplier)                  │   │  │
│  │  │    Stage 2: global cap (global_max_exposure_pct)        │   │  │
│  │  │  → Cycle spend cap                                      │   │  │
│  │  │  → Guardian cap (if TradingGuardian active)             │   │  │
│  │  └─────────────────────────────────────────────────────────┘   │  │
│  │                          ↓                                     │  │
│  │  ┌─────────────────────────────────────────────────────────┐   │  │
│  │  │ GATE LAYER 7: Hard Mode Guard (PATCH 2)                │   │  │
│  │  │  → If any SKIP/FAIL fired this cycle, block live orders │   │  │
│  │  │  → Fee sanity check (>25% of notional → skip)           │   │  │
│  │  └─────────────────────────────────────────────────────────┘   │  │
│  │                          ↓                                     │  │
│  │  ┌─────────────────────────────────────────────────────────┐   │  │
│  │  │ ORDER SUBMISSION                                        │   │  │
│  │  │  → POST /portfolio/orders (side, ticker, count, price)  │   │  │
│  │  │  → Record fill → TradeNotifier → Telegram               │   │  │
│  │  │  → Record fee → bankroll fee drag tracking              │   │  │
│  │  └─────────────────────────────────────────────────────────┘   │  │
│  │                          ↓                                     │  │
│  │  ┌─────────────────────────────────────────────────────────┐   │  │
│  │  │ POST-TRADE                                              │   │  │
│  │  │  → Stale order cancellation (>120s)                     │   │  │
│  │  │  → Coverage summary (all 5 assets logged)               │   │  │
│  │  │  → Exposure cap assertions                              │   │  │
│  │  │  → Schema drift detection (3+ missing streaks)          │   │  │
│  │  │  → Telegram digest flush                                │   │  │
│  │  └─────────────────────────────────────────────────────────┘   │  │
│  └────────────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────────┘
```

---

## 2. Strike Distance Parameter — Current State

### Where `max_strike_distance_pct` Lives Today

| Location | Value | Tiered? | Notes |
|---|---|---|---|
| `TraderConfig.max_strike_distance_pct` | `0.125` (12.5%) | **No** — flat | Default in dataclass; overridable via `KALSHI_TRADER_MAX_DISTANCE` env var |
| `TraderConfig.from_env()` | `float(os.getenv("KALSHI_TRADER_MAX_DISTANCE", "0.125"))` | **No** | Single env var, no per-asset override |
| `_STRIKE_BAND_PCT` (class var on CT) | Per (asset, tf) dict | **Yes** — 15 entries | Used **only** by `_max_strike_distance_for()` and post-trade assertions |
| `FilterPipeline.default_max_strike_distance_pct` | `1.0` (100%) | **Disabled** | Distance filtering in FP is intentionally no-op |
| `NearSpotSelector.select_near_spot()` call | `max_distance_pct=self.config.max_strike_distance_pct` | **No** — flat 12.5% | This is the **active** distance gate |
| `KalshiRiskConfig` | ❌ **Not present** | N/A | Target for refactor |

### The Duplication / Inconsistency Problem

There are **two** independent strike-distance systems:

1. **`_STRIKE_BAND_PCT`** (tiered, per asset×tf, hardcoded dict on the class)
   - Used by `_max_strike_distance_for()` → only consumed by **post-trade assertion** logic (lines ~1947-1973)
   - Also validated in `_validate_asset_wiring()` at startup (warning only)
   - **Missing entries**: weekly timeframe for all assets → falls back to flat 12.5%

2. **`config.max_strike_distance_pct`** (flat, from `TraderConfig`)
   - Passed to `NearSpotSelector.select_near_spot(max_distance_pct=...)` → this is the **real** filter
   - Applies uniformly to BTC, ETH, SOL, XRP, DOGE across all timeframes

**Result**: The tiered bands in `_STRIKE_BAND_PCT` (e.g., BTC-15m = 3%, DOGE-daily = 25%) are **only used for post-trade assertions** — the actual filtering uses the flat 12.5%. This means:
- BTC-15m assertions expect ±3% but the filter allows ±12.5% → assertion will never fire
- DOGE-daily allows ±25% in assertions but filter blocks at ±12.5% → valid candidates dropped

---

## 3. Blocker Table

| # | Blocker | Severity | Location | Impact | Fix Effort |
|---|---|---|---|---|---|
| B1 | **`max_strike_distance_pct` is flat, not tiered** | 🔴 High | `NearSpotSelector` call in CT line ~1701-1707 | BTC-15m gets ±12.5% (too wide; should be ±3%). DOGE-daily gets ±12.5% (too tight; should be ±25%). Wrong candidates selected. | Medium |
| B2 | **`_STRIKE_BAND_PCT` is orphaned from actual filtering** | 🔴 High | CT class var lines ~1257-1263 | Tiered bands exist but are only used in post-trade assertions, not in the NearSpotSelector call. Two sources of truth. | Medium |
| B3 | **`KalshiRiskConfig` has no `max_strike_distance_pct`** | 🟡 Medium | `kalshi_risk_engine.py` | Can't query risk engine for distance config. TraderConfig owns it but shouldn't — it's a risk parameter. | Small |
| B4 | **`_STRIKE_BAND_PCT` missing weekly/monthly/annual entries** | 🟡 Medium | CT class var line ~1257 | Any weekly/monthly series falls back to flat 12.5% in assertions. No tiered coverage for longer tenors. | Small |
| B5 | **FilterPipeline distance filter disabled (100%)** | 🟢 Low | `kalshi_filter_pipeline.py` line ~50, CT line ~1670 | Intentional: FP passes everything, NearSpotSelector does real filtering. But confusing — dead config param. | Trivial |
| B6 | **Post-trade assertion uses `_STRIKE_BAND_PCT` but filter uses flat** | 🔴 High | CT lines ~1947-1973 | Assertion bands don't match actual filter bands → assertions can false-positive or never fire. | Medium (fix with B1) |
| B7 | **`to_risk_config()` doesn't map `max_strike_distance_pct`** | 🟡 Medium | `TraderConfig.to_risk_config()` lines ~177-208 | The risk config built from TraderConfig has no distance field. Risk engine can't enforce or report on distance. | Small |

---

## 4. Top 3 Blockers — Recommended Fix Order

### Blocker 1: Unify tiered strike distance into `KalshiRiskConfig` (B1 + B3 + B7)

**Problem**: `max_strike_distance_pct` is a flat 12.5% in `TraderConfig`, passed raw to `NearSpotSelector`. The tiered `_STRIKE_BAND_PCT` dict is orphaned.

**Fix**:
1. Add `max_strike_distance_grid: Dict[Tuple[str,str], float]` and `max_strike_distance_default: float = 0.125` to `KalshiRiskConfig`.
2. Add `get_max_strike_distance(asset, timeframe) -> float` method to `KalshiRiskEngine`.
3. Remove `max_strike_distance_pct` from `TraderConfig`.
4. In CT `_run_cycle_inner()`, replace the flat `max_distance_pct=self.config.max_strike_distance_pct` with a per-candidate lookup via the risk engine.

**Challenge**: `NearSpotSelector.select_near_spot()` takes a single `max_distance_pct` float. To support per-asset tiering, either:
- (a) Call `select_near_spot` once per asset with the appropriate distance, or
- (b) Push the tiered lookup into `select_near_spot_best_edge()` (alongside the existing `use_tiered_min_edge` / `use_tiered_max_price` pattern).

Option (b) is cleaner — add `use_tiered_max_distance: bool` + `max_distance_grid` param, mirroring the existing tiered edge/price pattern.

### Blocker 2: Kill `_STRIKE_BAND_PCT` duplication (B2 + B4 + B6)

**Problem**: Two independent distance systems. `_STRIKE_BAND_PCT` is only used for post-trade assertions, not actual filtering. Missing weekly/monthly/annual entries.

**Fix**:
1. After Blocker 1 is done, delete `_STRIKE_BAND_PCT` from CT.
2. Delete `_max_strike_distance_for()` method.
3. Update post-trade assertions to read from `KalshiRiskEngine.get_max_strike_distance()`.
4. Populate the grid in `KalshiRiskConfig` with all 5 assets × 6 timeframes (15m, 1h, daily, weekly, monthly, annual).

### Blocker 3: Add `MAX_STRIKE_DISTANCE_GRID` to `market_filter.py` (new tiered grid)

**Problem**: `MIN_EDGE_GRID` and `MAX_PRICE_GRID` already live in `market_filter.py` with `assert_exact_assets()` enforcement. Strike distance should follow the same pattern for consistency and CI protection.

**Fix**:
1. Add `MAX_STRIKE_DISTANCE_GRID: Dict[str, Dict[str, float]]` to `market_filter.py`, structured identically to `MIN_EDGE_GRID`.
2. Add `get_tiered_max_strike_distance(asset, series_ticker) -> float` helper.
3. Add `assert_exact_assets(set(MAX_STRIKE_DISTANCE_GRID.keys()), "MAX_STRIKE_DISTANCE_GRID")`.
4. Wire `select_near_spot_best_edge()` to use this grid when `use_tiered_max_distance=True`.
5. `KalshiRiskConfig` can either own the grid or delegate to `market_filter.py` — preferring the latter for consistency with min_edge/max_price.

---

## 5. Hidden Clamps & Safety Hacks Found

| Clamp | Location | Behavior |
|---|---|---|
| **PATCH 2: Hard Mode Guard** | CT lines ~1497, 2185, 2200 | If any fee sanity check fails this cycle, blocks ALL remaining live orders. Resets per cycle. |
| **PATCH 3: Spot Feed Degraded** | CT lines ~1499, 1896 | If spot sources are stale/degraded, blocks all new entries. |
| **Smoke Test Mode** | `TraderConfig.from_env()` lines ~214-245 | `KALSHI_TRADER_SMOKE_TEST=true` relaxes min_edge to 1%, max_price to 99¢, max_position to 1. Blocked if PM is live. |
| **PM Live Gate** | `_live_api_orders_allowed()` lines ~1079-1108 | Blocks live Kalshi orders unless `MERID_PM_TRADING_MODE=live` or `KALSHI_CT_BYPASS_PM_LIVE_GATE=true`. |
| **Guardian Cap** | Guard system periodic re-check | `TradingGuardian` can override sizing caps and force observation mode. Re-checked every 300s. |
| **FilterPipeline distance = 100%** | CT line ~1670 | Distance filter in FP intentionally disabled — all distance filtering delegated to NearSpotSelector. |
| **RTI Quarantine** | `kalshi_filter_pipeline.py` lines ~271-281 | Markets flagged by CFB quarantine are silently dropped before candidate generation. |

---

## 6. Module Map (Key Files)

| Module | Role |
|---|---|
| `merid/trading/kalshi_continuous_trader.py` | Main trading loop, config, exposure gates, order submission |
| `merid/trading/kalshi_filter_pipeline.py` | Stage 1 filter: liquidity, expiry, parse, candidate gen |
| `merid/event_venues/kalshi/market_filter.py` | Stage 2 filter: NearSpotSelector, tiered grids (edge, price), overlap grouping |
| `merid/prediction/risk/kalshi_risk_engine.py` | Risk config + engine: sizing, drawdown, fee drag, Kelly |
| `merid/trading/crypto_spot_service.py` | Multi-source spot prices with fallback |
| `merid/signals/crypto_15m_indicators.py` | Indicator stack: EMA, RSI, MACD, ATR, vol |
| `core/execution_gate.py` | Execution gate: kill switches, recon, price feeds |
| `merid/guards/__init__.py` | TradingGuardian: upstream/mid/downstream guard checks |
| `config/kalshi_universe.py` | KALSHI_CRYPTO_PRODUCTS, series tickers, asset lists |
| `config/kalshi_crypto_config.py` | ACTIVE_CRYPTO_ASSETS canonical list |
| `merid/event_venues/kalshi/constants.py` | `assert_exact_assets()` grid coverage enforcement |

---

## 7. Proposed `MAX_STRIKE_DISTANCE_GRID` Values

Based on `_STRIKE_BAND_PCT` plus extrapolation for missing timeframes:

```python
MAX_STRIKE_DISTANCE_GRID: Dict[str, Dict[str, float]] = {
    "BTC": {
        "15m": 0.03,   "1h": 0.06,   "daily": 0.12,
        "weekly": 0.15, "monthly": 0.20,
    },
    "ETH": {
        "15m": 0.04,   "1h": 0.08,   "daily": 0.15,
        "weekly": 0.18, "monthly": 0.22,
    },
    "SOL": {
        "15m": 0.05,   "1h": 0.10,   "daily": 0.18,
        "weekly": 0.22, "monthly": 0.28,
    },
    "XRP": {
        "15m": 0.06,   "1h": 0.12,   "daily": 0.20,
        "weekly": 0.25, "monthly": 0.30,
    },
    "DOGE": {
        "15m": 0.08,   "1h": 0.15,   "daily": 0.25,
        "weekly": 0.30, "monthly": 0.35,
    },
}
MAX_STRIKE_DISTANCE_GLOBAL_FALLBACK: float = 0.125
```

Rationale:
- 15m/1h/daily values match existing `_STRIKE_BAND_PCT`
- Weekly/monthly extrapolated from daily with ~25% widening per tenor step
- Noisier assets (DOGE > XRP > SOL > ETH > BTC) get wider bands

---

## 8. BTC-Anchored Cross-Asset Move Model

### Problem

The edge model's `expected_move` is computed independently per asset using that
asset's own realized vol (`vol_ann`). This ignores the dominant reality of crypto
markets: **alt-coins co-move with BTC**. When BTC is volatile, ETH/SOL/XRP/DOGE
move proportionally more (beta > 1), but the per-asset realized vol may lag behind
BTC's current-period move.

### Formula

For each asset A ∈ {ETH, SOL, XRP, DOGE} and timeframe T:

```
r_A ≈ α_{A,T} + β_{A,T} · r_BTC + ε

β_{A,T} = Cov(r_A, r_BTC) / Var(r_BTC)     (OLS slope)
α_{A,T} = mean(r_A) - β · mean(r_BTC)       (intercept)
```

Given current spot prices P_BTC, P_A and a BTC move ΔP_BTC:

```
r_BTC  = ΔP_BTC / P_BTC
ΔP_A   ≈ β_{A,T} · r_BTC · P_A
```

Example: BTC at $84,000 moves +$250 → r_BTC ≈ 0.30%. With β_ETH ≈ 1.5:
- ETH at $2,100 → expected ΔP_ETH ≈ 1.5 × 0.003 × 2100 ≈ **$9.45**

### Integration into CT Edge Model

The blending formula in `_compute_edge()`:

```
adjusted_expected_move = w · |β · r_BTC| + (1-w) · base_expected_move

where w = min(R², 0.70)    # lean on beta only as much as it explains
      floor = 0.5 × base   # never shrink below 50% of independent estimate
```

This means:
- With R² = 0.80, the model uses 70% BTC-anchored + 30% independent vol
- With R² = 0.15, the model uses 15% BTC-anchored + 85% independent vol
- With insufficient data (prior mode), no adjustment is applied

### Prior Betas (cold-start)

Until enough observations accumulate (default: 20), the model uses empirical
priors from 2025 crypto data:

| Asset | 15m  | 1h   | daily | weekly |
|-------|------|------|-------|--------|
| BTC   | 1.00 | 1.00 | 1.00  | 1.00   |
| ETH   | 1.15 | 1.20 | 1.25  | 1.30   |
| SOL   | 1.40 | 1.50 | 1.55  | 1.60   |
| XRP   | 1.10 | 1.25 | 1.35  | 1.40   |
| DOGE  | 1.30 | 1.45 | 1.60  | 1.70   |

Prior betas are **not** used for blending (they return `base_expected_move`
unchanged) — they only serve as fallback for `expected_dollar_move()` and
`suggested_strike_distance_pct()` queries.

### Conditional Bands (non-linear regime awareness)

The model also buckets BTC moves by magnitude and reports average/median alt
response in each bucket:

| Bucket        | Description                          |
|---------------|--------------------------------------|
| 0–0.25%       | Noise — alts track loosely           |
| 0.25–0.5%     | Light move — β applies               |
| 0.5–1.0%      | Standard move — β reliable           |
| 1.0–2.0%      | Strong move — may see β amplification|
| 2.0–5.0%      | Large move — non-linear effects      |
| 5%+           | Extreme — regime break possible      |

### Module Map

| File | Role |
|---|---|
| `merid/signals/btc_anchored_move.py` | Model: OLS beta, conditional bands, singleton |
| `merid/trading/kalshi_continuous_trader.py` | CT integration: init (line ~512), spot feed (line ~1546), edge blend (line ~1355) |
| `merid/risk/correlation.py` | Existing correlation tracker (pairwise ρ, exposure reduction) |
| `tests/test_btc_anchored_move.py` | 32 tests: regression, priors, bands, blending, threading |

### Strike Distance Suggestion

The model provides `suggested_strike_distance_pct()` which can replace the
orphaned `_STRIKE_BAND_PCT` with a dynamic, BTC-vol-aware band:

```
alt_atr_implied = β · btc_atr_pct
suggested = max(base_distance, 2 × alt_atr_implied)
capped = min(suggested, 3 × base_distance)
```

This is not yet wired into the NearSpotSelector distance filter (blocked by
the flat `max_strike_distance_pct` issue documented in Section 3, Blocker B1).
Once the tiered `MAX_STRIKE_DISTANCE_GRID` is implemented in `market_filter.py`,
this method can dynamically adjust bands based on current BTC volatility.
