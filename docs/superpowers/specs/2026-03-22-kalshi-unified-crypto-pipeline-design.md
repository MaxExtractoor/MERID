# Kalshi Unified Crypto Pipeline — Wiring Design
**Date:** 2026-03-22
**Status:** Approved for implementation
**Scope:** Wire the existing swarm pipeline into KalshiContinuousTrader so signals flow TradingAgent → event_bus → KalshiContinuousTrader → route_order_async, across all live Kalshi crypto products (BTC/ETH/SOL/XRP/DOGE, all active timeframes), with full paper/live/hybrid mode via VenueGate.

---

## 1. Goal

KalshiContinuousTrader currently operates as an independent silo with its own simplistic edge model (`_compute_edge` — linear, BTC-only, no swarm input) and its own spot price fetcher (`_get_btc_spot` — CoinGecko/Coinbase/Binance, BTC only). TradingAgent and the SwarmConsensusEngine produce directional signals that are fully disconnected from the execution engine.

**Target state:** A single signal path where:
- TradingAgent (swarm-approved signals) is the sole source of directional edge
- KalshiContinuousTrader is the sole execution and bankroll engine
- No direct REST orders from signal generators
- VenueGate governs paper/live mode across both components
- RTI-derived settlement proxy feeds EdgeModel to reduce settlement price divergence

---

## 2. Existing Infrastructure (Verified)

All of the following exist and are production-ready. No reinvention needed.

| Component | File | Status |
|---|---|---|
| Async pub/sub event bus | `core/event_bus.py` | Ready — `subscribe()`/`publish()` |
| Unified signal schema | `merid/signals/unified_schema.py` | Ready — `UnifiedSignal` dataclass |
| Signal SQLite store | `merid/signals/store.py` | Ready — 6 tables, needs 2 more |
| RTI stream (CF Benchmarks proxy) | `merid/data/rti_stream.py` | Ready — `rti_60s_sma` = settlement proxy |
| Crypto RTI monitor | `merid/risk/crypto_rti_monitor.py` | Ready — feeds regime agents + risk alerts |
| VenueGate (mode enforcement) | `merid/prediction/venue_gate.py` | Ready — MOCK/PAPER/LIVE, MERID_ALLOW_LIVE_TRADES guard |
| SwarmConsensusEngine (wired) | `merid/swarm/consensus_engine.py` | Ready — gate inserted in trading_agent.py Phase 16 |
| KalshiContinuousTrader | `merid/trading/kalshi_continuous_trader.py` | Ready — bankroll/Kelly/liquidity, needs signal subscription |
| TradingAgent | `merid/prediction/trading_agent.py` | Ready — SwarmConsensusEngine gate active, needs event_bus publish |
| Reflection system | `agents/reflection/` | Initialized in lifespan, periodic trigger missing |
| Crypto product config | `config/crypto_spot_kalshi_config.py` | Ready — `CRYPTO_CONFIG` with BTC/ETH/SOL/XRP/DOGE |
| Per-asset regime agents | `merid/agents/btc_15m_agent.py` et al. | Ready — consume RTI, produce AgentOpinion |
| Continuous trader API | `web/api/kalshi_continuous_trader_api.py` | Ready — status/stop endpoints exist |

---

## 3. Confirmed Gaps

### GAP-1: KalshiContinuousTrader is a signal silo
**Root cause:** `_run_cycle()` calls its own `_compute_edge()` (simple linear model, 50/50 for directional markets) and `_get_btc_spot()` (CoinGecko/Coinbase/Binance, BTC-only). Never reads TradingAgent output, never subscribes to event_bus.
**Effect:** Swarm consensus, EdgeModel ensemble, RTI regime signals are all ignored at execution time.

### GAP-2: TradingAgent never publishes to event bus
**Root cause:** After SwarmConsensusEngine approval in `_execute_signal_body()`, TradingAgent calls `route_order_async` directly without publishing a signal to `core/event_bus.py`.
**Effect:** No channel for KalshiContinuousTrader to subscribe to swarm-approved signals.

### GAP-3: LivePriceFeed broken in KALSHI_ONLY mode
**Root cause:** `data/live_price_feed.py` line 104–107 — `_initialize_exchanges()` returns early when `settings.KALSHI_ONLY=True`. EdgeModel's `_spot_relative_probability` returns `(None, 0.0)`. CoinGecko fallback (`_fetch_from_coingecko`) only maps BTC/ETH/SOL/AVAX — no XRP, no DOGE.
**Effect:** EdgeModel in production runs on spread + time_decay signals only; no spot-relative probability for any asset.

### GAP-4: Settlement price divergence — RTI not fed to EdgeModel
**Root cause:** `CryptoRTIMonitor` maintains `rti_60s_sma` (CF Benchmarks 60s rolling mean — Kalshi's exact settlement definition). `EdgeModel` uses Kraken/Coinbase spot last price instead. These diverge 0.2–1% near expiry.
**Effect:** Edge calculations near settlement are systematically miscalibrated for threshold markets.

### GAP-5: KALSHI_CRYPTO_PRODUCTS config drift
**Root cause:** `config/kalshi_universe.py` `KALSHI_CRYPTO_PRODUCTS` has placeholder series tickers (e.g. `KXBT-1H-UPDOWN` — wrong format), while `config/crypto_spot_kalshi_config.py` `CRYPTO_CONFIG` has the correct series codes (e.g. `KXBTCH1`, `KXDOGEH1`). Both exist independently; neither is derived from the other.
**Effect:** KalshiContinuousTrader (imports `KALSHI_CRYPTO_PRODUCTS`) and TradingAgent (may reference `CRYPTO_CONFIG`) operate on different market universe definitions. DOGE_15M entry exists but Kalshi has no 15m DOGE series.

### GAP-6: Signal persistence — no approved_signals / orders linkage
**Root cause:** `merid/signals/store.py` has no `approved_signals` table and no `orders` linkage table.
**Effect:** Cannot audit "which swarm signal led to which order" — required for PnL attribution and reflection.

### GAP-7: UnifiedSignal missing settlement fields
**Root cause:** `merid/signals/unified_schema.py` `UnifiedSignal` has no `settlement_spec_id` or `edge_normalized` field.
**Effect:** Cannot link a signal to its settlement specification (which series/expiry defines settlement) or store normalized edge for cross-asset comparison.

### GAP-8: Continuous trader not auto-started from lifespan
**Root cause:** `web/main.py` lifespan does not call `get_continuous_trader()` or schedule `trader.run()`. The trader is only accessible via API endpoint; it must be manually started.
**Effect:** Server restarts require manual API call to resume execution.

### GAP-9: Reflection system not triggered periodically
**Root cause:** `agents/reflection/` system is initialized in lifespan but no periodic `asyncio` task triggers reflection cycles.
**Effect:** Reflection layer that could catch drift/degradation never fires.

### GAP-10: Frontend constants missing for continuous trader
**Root cause:** `web/react/src/config/constants.ts` has no `KALSHI_CONTINUOUS_TRADER_STATUS` or `KALSHI_CONTINUOUS_TRADER_STOP` constants, though `web/react/src/components/KalshiBankrollPanel.tsx` references both.
**Effect:** Bankroll panel references undefined constants; compilation/runtime error under strict typing.

---

## 4. Required Changes

### Phase 1 — Config consolidation (prerequisite for everything else)

**File:** `config/kalshi_universe.py`
- Derive `KALSHI_CRYPTO_PRODUCTS` from `CRYPTO_CONFIG` (import from `config/crypto_spot_kalshi_config.py`)
- Format: `{ asset: { timeframe: series_ticker } }` derived from `CRYPTO_CONFIG[asset]["series"]`
- DOGE: include `1h` and `1d` only; mark DOGE `15m` as `status="planned"` comment — do NOT add to active series dict

**File:** `config/crypto_spot_kalshi_config.py`
- Add `"settlement_source": "cf_benchmarks_rti"` and `"settlement_window_sec": 60` to each asset entry
- This documents the settlement definition explicitly and enables EdgeModel to select the correct price source near expiry

### Phase 2 — Price feed fix (KALSHI_ONLY mode + XRP/DOGE gap)

**File:** `data/live_price_feed.py` — `_fetch_from_coingecko()`
- Add XRP (`ripple`) and DOGE (`dogecoin`) to the CoinGecko mapping
- Note: AVAX can stay; SOL is already mapped

**File:** `merid/prediction/edge_model.py` — `_spot_relative_probability()`
- Add RTI fallback: when `self._price_feed` is None OR returns stale/empty data, try `CryptoRTIMonitor.get_metrics(asset).rti_60s_sma` as spot proxy
- When `minutes_to_expiry < 5`: weight RTI signal at 0.8 (Kalshi settles on RTI; near expiry it IS the settlement price)
- This resolves both GAP-3 (KALSHI_ONLY mode) and GAP-4 (settlement divergence)
- Import pattern: `try: from merid.risk.crypto_rti_monitor import get_crypto_rti_monitor; rti = get_crypto_rti_monitor().get_metrics(asset); except: rti = None`

### Phase 3 — Signal schema + persistence

**File:** `merid/signals/unified_schema.py`
- Add `settlement_spec_id: Optional[str] = None` to `UnifiedSignal` — format: `"{series_ticker}:{expiry_ts}"`
- Add `edge_normalized: Optional[float] = None` — edge as a fraction of fair prob (dimensionless, cross-asset comparable)

**File:** `merid/signals/store.py`
- Add `approved_signals` table: `(id, signal_id, asset, timeframe, side, edge_normalized, settlement_spec_id, approved_at, swarm_approval_reason)`
- Add `orders` linkage table: `(id, signal_id, order_id, ticker, qty, price_cents, side, placed_at, status)`
- These two tables enable the reflection system to compute post-hoc accuracy

### Phase 4 — Event bus wiring (the core integration)

**File:** `merid/prediction/trading_agent.py` — `_execute_signal_body()` (after SwarmConsensusEngine gate, before `route_order_async`)
- Publish `ApprovedSignal` to event_bus channel `signals.crypto.{asset}.{tenor}`:
  ```python
  signal = UnifiedSignal(
      asset=asset, tenor=timeframe, side=action,
      edge=float(edge_value), confidence=confidence,
      settlement_spec_id=f"{series_ticker}:{expiry_ts}",
      edge_normalized=float(edge_normalized),
      source="trading_agent",
  )
  await event_bus.publish(f"signals.crypto.{asset}.{timeframe}", signal)
  ```
- Keep `route_order_async` call in place as fallback for BTC15m (the original path); KalshiContinuousTrader subscription is additive, not a replacement in Phase 4

**File:** `merid/trading/kalshi_continuous_trader.py` — `__init__` and `run()`
- Subscribe to `signals.crypto.*` channels via `event_bus.subscribe()`
- On signal receipt: validate via VenueGate, compute Kelly sizing (existing `_compute_kelly_qty`), apply correlation cap, place via `route_order_async`
- `_compute_edge()` is kept for markets not covered by swarm signals (fallback) — directional markets should update to use swarm signal side when available
- `_get_btc_spot()` promoted to `_get_asset_spot(asset)` — reuse `LivePriceFeed.get_current_price(f"{asset}/USDT")` first; fall back to CoinGecko per-asset

### Phase 5 — Lifespan wiring

**File:** `web/main.py` — lifespan startup
- Add: `trader = get_continuous_trader(); _tasks.append(asyncio.create_task(trader.run()))`
- Add periodic reflection trigger: `asyncio.create_task(_periodic_reflection(interval_sec=3600))` — calls reflection engine's `run_reflection_cycle()` every hour

### Phase 6 — Frontend constants

**File:** `web/react/src/config/constants.ts`
- Add:
  ```typescript
  KALSHI_CONTINUOUS_TRADER_STATUS: '/api/v1/kalshi/continuous-trader/status',
  KALSHI_CONTINUOUS_TRADER_STOP: '/api/v1/kalshi/continuous-trader/stop',
  ```
- Verify these match the routes registered in `web/api/kalshi_continuous_trader_api.py`

---

## 5. Not In Scope

- **Social bot integration** — Telegram/Twitter signal publishing is already wired in Phase 13b
- **UI component changes** — `KalshiBankrollPanel`, `KalshiTerminalView` already reference the correct endpoints; no layout changes needed
- **Paper session persistence** — already fixed (BUG R, Phase 15)
- **AgentPerformanceTracker** — already fixed (BUG W, Phase 16)
- **`route_order_async` internals** — executor, execution_guard, and order_router already production-hardened
- **New Kalshi series onboarding** — DOGE 15m, weekly contracts — tracked as `status="planned"` in config; no code changes

---

## 6. Asset / Timeframe Matrix

| Asset | 15m | 1h | Daily | Notes |
|---|---|---|---|---|
| BTC | ✅ KXBTC15M | ✅ KXBTCH1 | ✅ KXBTCD1 | Full coverage |
| ETH | ✅ KXETH15M | ✅ KXETHH1 | ✅ KXETHD1 | Full coverage |
| SOL | ✅ KXSOL15M | ✅ KXSOLH1 | ✅ KXSOLD1 | Full coverage |
| XRP | ✅ KXXRP15M | ✅ KXXRPH1 | ✅ KXXRPD1 | Full coverage |
| DOGE | ❌ (no Kalshi series) | ✅ KXDOGEH1 | ✅ KXDOGED1 | 15m planned |

---

## 7. VenueGate Mode Behaviour

| MERID_PM_TRADING_MODE | MERID_ALLOW_LIVE_TRADES | Behaviour |
|---|---|---|
| `mock` | any | No orders placed; signals logged only |
| `paper` | any | PaperSession fills; bankroll tracked in paper state |
| `live` | not set | Silently falls back to PAPER (VenueGate setter guard) |
| `live` | `true` | Live REST orders via route_order_async |

---

## 8. Test Plan

- **Unit:** `test_event_bus_signal_flow.py` — publish ApprovedSignal, assert KalshiContinuousTrader handler receives it
- **Unit:** `test_edge_model_rti_fallback.py` — mock LivePriceFeed as empty, assert EdgeModel uses RTI `rti_60s_sma` as spot proxy; near-expiry (< 5 min) assert RTI weight = 0.8
- **Unit:** `test_kalshi_universe_derived.py` — assert `KALSHI_CRYPTO_PRODUCTS` keys match `CRYPTO_CONFIG` keys; assert DOGE_15M absent from active series
- **Unit:** `test_signal_store_linkage.py` — write approved_signal, write linked order, assert JOIN query returns both
- **Integration:** `test_continuous_trader_wiring.py` — existing test; add assertion that status endpoint returns `subscribed_channels: ["signals.crypto.*"]`
- **E2E (paper mode):** Start lifespan with `MERID_PM_TRADING_MODE=paper`, publish a mock ApprovedSignal, assert bankroll state updates and PaperSession records a fill
