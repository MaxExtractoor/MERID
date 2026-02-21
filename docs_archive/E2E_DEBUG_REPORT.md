# MERID End-to-End System Debug Report

**Generated:** 2026-02-13T20:35 UTC-05:00  
**Environment:** development  
**Global Trading Mode:** OFFLINE (spectator=True)  
**Pipeline Venue Modes:** Crypto=SIM, Equity=PAPER, Prediction=SIM  

---

## 1. Executive Summary

MERID is running in **OFFLINE/spectator mode** with **no API keys configured** (no `.env` file, no OS environment variables for any exchange). Despite this, the system is partially functional:

- **Price feeds:** CoinGecko REST feed is working (66 assets, real prices). CCXT exchange feeds are initialized but silently failing (all fetches fail, errors logged at DEBUG level).
- **Swarm agents:** 8 agents reported via manifest fallback. The AgentOrchestrator starts 7 real agent instances (twitter, telegram, news, arbitrage, execution, slippage + price_feed) but most are disabled/no-op without API keys.
- **Routing/Execution:** TradeRouter has 0 registered adapters. Pipeline ModeManager has 7 venues configured but no actual adapter implementations are wired. No proposals have been generated.
- **Prediction Markets:** Kalshi connector initialized but returns 0 markets (no API key → falls back to mock data, but mock data isn't populating `_all_markets`).
- **UI:** Dashboard shows real CoinGecko prices, paper engine portfolio ($93,200 equity), and agent manifest data. WebSocket connections fail through Vite proxy but REST fallbacks cover it.
- **Telemetry:** SLI endpoint works but shows 0 events (frontend telemetry beacon not reaching backend through proxy).

**Overall Health: DEGRADED** — Price data flows, but no trading, no real agent activity, no prediction markets, and no venue adapters are operational.

---

## 2. Happy-Path Flow Verification

### Flow 1: CoinGecko → Dashboard → UI Watchlist
**Status: PASS ✅**

| Step | Evidence |
|---|---|
| CoinGecko API call | `fetch_live_prices()` → 66 assets fetched, `_price_cache` populated |
| `/api/prices/live?symbols=BTC,ETH,SOL,AVAX` | Returns BTC=$68,976, ETH=$2,053, SOL=$84.92, AVAX=$9.19 (source: coingecko) |
| `/api/v1/live/prices` | Returns 66 assets with real prices, volumes, market caps |
| Frontend `Overview.tsx` | Polls `PRICES_LIVE` every 10s → watchlist renders real prices |

**Discrepancy:** The `high_24h` and `low_24h` fields are synthetic (`price * 1.02` / `price * 0.98`) rather than real CoinGecko data. CoinGecko's `/simple/price` endpoint doesn't include high/low — would need `/coins/markets` for that.

### Flow 2: CCXT → LivePriceFeed → Paper Engine Mark-to-Market
**Status: FAIL ❌**

| Step | Evidence |
|---|---|
| Exchange init | 6 exchanges initialized (Kraken, Coinbase, Gemini, Binance, Bybit, OKX) — all "configured" or "public only" |
| `start_streaming()` task | Created at startup but "Price streaming started" log never appears in backend output |
| `fetch_and_broadcast_prices()` | Never executes successfully — 0 items in `LivePriceFeed.price_cache` |
| Paper engine subscription | `PaperTradingEngine subscribed to live price feed` logged, but no price updates received |

**Root Causes:**
1. **No API keys** — All exchange API keys are `None`. CCXT initializes with empty/public config, but many symbols require authenticated endpoints or fail with rate limits on public endpoints.
2. **Silent failures** — CCXT `fetch_ticker` errors are logged at `DEBUG` level (invisible at `INFO`). After `max_retries` attempts per exchange, falls through to CoinGecko fallback within LivePriceFeed, but that fallback only covers 4 symbols (BTC, ETH, SOL, AVAX).
3. **Streaming task scheduling** — The `asyncio.create_task(price_feed.start_streaming())` is created but the event loop may not yield to it during the long synchronous startup sequence. The AgentOrchestrator's `start()` also calls `price_feed.start_streaming()` (duplicate).

### Flow 3: Swarm Agent → Proposal → TradeRouter → Execution
**Status: FAIL ❌**

| Step | Evidence |
|---|---|
| Agent orchestrator | Started as background task with 7 agents |
| Orchestration loop | Runs `_check_arbitrage_opportunities()`, `_monitor_market_conditions()`, `_post_periodic_updates()` |
| Proposal generation | 0 proposals in `/api/v1/pipeline/proposals` |
| TradeRouter | 0 registered adapters in AdapterRegistry |
| Execution | No orders routed, no fills |

**Root Causes:**
1. **No adapters registered** — `AdapterRegistry` is empty. The pipeline's `UnifiedVenueAdapter` implementations exist in code but are never instantiated and registered at startup.
2. **No real market data for agents** — Arbitrage agent needs cross-exchange price data (CCXT feed is dead). Execution agent needs order book data (not available).
3. **Agents are mostly disabled** — Twitter, Telegram agents require API keys. News monitor may work but produces no actionable signals without downstream consumers.

### Flow 4: Kalshi → Prediction Markets → UI
**Status: FAIL ❌**

| Step | Evidence |
|---|---|
| KalshiConnector init | Initialized, `_api_key_id = None` |
| `fetch_markets()` | No API key → logs "No API key configured, using mock data" → returns mock markets |
| Aggregator `_all_markets` | 0 items (mock markets returned from `fetch_markets` but not stored in `_all_markets`) |
| `/api/v1/prediction-markets/summary` | Returns venue_gate info but 0 markets |
| UI | Shows "No Kalshi markets available — returning offline state" |

**Root Causes:**
1. **No Kalshi API key** — `KALSHI_API_KEY_ID` is `None`.
2. **Mock data not stored** — `KalshiConnector.fetch_markets()` returns mock markets, but the aggregator's `_fetch_all_markets()` may not be storing them in `_all_markets` correctly.

### Flow 5: Frontend Telemetry → Backend SLI
**Status: PARTIAL ⚠️**

| Step | Evidence |
|---|---|
| Frontend `logUiError` | Configured in `logger.ts` with `sendBeacon` |
| `POST /api/v1/telemetry` | Endpoint exists and works |
| SLI counters | `/api/v1/telemetry/sli` returns 0 events |
| Prometheus metrics | `/api/v1/telemetry/metrics` endpoint exists |

**Root Cause:** The Vite dev proxy may not forward `sendBeacon` POST requests correctly, or the frontend telemetry is disabled by default. The `setTelemetryEnabled` toggle may need to be explicitly enabled.

---

## 3. External Connectivity Audit

### Venue-by-Venue Status

| Venue | Domain | API Key | Feed Status | Adapter | Notes |
|---|---|---|---|---|---|
| **CoinGecko** | Market Data | Not needed | ✅ Working | N/A | 66 assets, 10s refresh, real prices |
| **Kraken** | Crypto | ❌ None | ❌ CCXT init OK, fetch fails | ❌ Not registered | Public ticker may work without key |
| **Coinbase** | Crypto | ❌ None | ❌ CCXT init OK, fetch fails | ❌ Not registered | Public ticker may work without key |
| **Binance** | Crypto | ❌ None | ❌ CCXT init OK, fetch fails | ❌ Not registered | US IP restrictions may apply |
| **Gemini** | Crypto | Not needed | ❌ CCXT init OK, fetch fails | ❌ Not registered | Public only, should work |
| **Bybit** | Crypto | ❌ None | ❌ CCXT init OK, fetch fails | ❌ Not registered | |
| **OKX** | Crypto | ❌ None | ❌ CCXT init OK, fetch fails | ❌ Not registered | |
| **Kalshi** | Prediction | ❌ None | ❌ No API key, mock fallback | ❌ Not registered | Public market list doesn't require auth |
| **Alpaca** | Equity | ❌ None | ⚠️ REST client init logged | ❌ Not registered | Paper mode configured |
| **IBKR** | Equity | ❌ None | ❌ Not connected | ❌ Not registered | Paper mode configured |

### Key Finding: CCXT Public Tickers Should Work

CCXT exchanges like Kraken, Coinbase, Gemini support **public ticker fetches without API keys**. The `_initialize_exchanges` correctly filters out `None` keys (line 157: `filtered_config = {k: v for k, v in config.items() if v is not None}`). The issue is likely:
- Symbol format mismatches (e.g., `BTC/USDT` not available on Kraken, which uses `BTC/USD`)
- Rate limiting on public endpoints
- The streaming task not actually running

---

## 4. Ingestion → Internal State Trace

### Price Data Flow

```
CoinGecko API ──→ web.api.live_data._price_cache (66 assets) ──→ /api/v1/live/prices ✅
                                                                ──→ /api/prices/live (fallback) ✅
                                                                
CCXT Exchanges ──→ data.live_price_feed.price_cache (0 items) ──→ /api/prices/live (primary, empty) ❌
                                                               ──→ PaperTradingEngine (subscriber, no updates) ❌
```

### Order/Position Data Flow

```
PaperTradingEngine ──→ 74 portfolios, 1 active position ──→ /api/portfolio/summary ✅
                                                          ──→ /ws/risk (real equity/PnL) ✅
                                                          ──→ /ws/trades (position snapshot) ✅
```

### Agent Data Flow

```
agents.registry (empty) ──→ fallback to _get_fallback_agents() ──→ /api/agents/summary (8 agents) ✅
                                                                ──→ /api/v1/agents/health (8 agents ONLINE) ✅
AgentOrchestrator (7 agents) ──→ orchestration_loop running ──→ no proposals generated ❌
```

### Schema Issues Found
- **`high_24h` / `low_24h`** in CoinGecko cache are synthetic (±2% of price), not real
- **`has_credentials: true`** in pipeline venues is from ModeManager defaults, not actual key validation
- **Agent `status: ONLINE`** is fallback data, not live heartbeat

---

## 5. Swarm & Agent Behavior

### Agent Status Table

| Agent | Type | Scheduled | Seeing Data | Producing Output | Last Error |
|---|---|---|---|---|---|
| analyst-gemma-01 | Analyst | ✅ Manifest | ❌ No price feed | ❌ No signals | N/A (fallback) |
| analyst-llama-01 | Analyst | ✅ Manifest | ❌ No price feed | ❌ No signals | N/A (fallback) |
| skeptic-01 | Risk Manager | ✅ Manifest | ❌ No price feed | ❌ No evaluations | N/A (fallback) |
| risk-01 | Risk Manager | ✅ Manifest | ❌ No price feed | ❌ No evaluations | N/A (fallback) |
| synthesizer-01 | Coordinator | ✅ Manifest | ❌ No inputs | ❌ No consensus | N/A (fallback) |
| archivist-01 | Researcher | ✅ Manifest | ❌ No data | ❌ No research | N/A (fallback) |
| strategy-agent-01 | Trader | ✅ Manifest | ❌ No price feed | ❌ No proposals | N/A (fallback) |
| meta-audit-01 | Governance | ✅ Manifest | ❌ No data | ❌ No audits | N/A (fallback) |

**Key Issue:** All 8 agents shown in the UI are **manifest fallback data**, not live agent instances. The actual `AgentOrchestrator` runs 7 different agents (twitter, telegram, news, arbitrage, execution, slippage, price_feed) but these are not reflected in the `/api/agents/summary` endpoint.

---

## 6. Routing, Resilience & Execution

### Resilience Layer
- **Circuit breakers:** 0 registered (no venue adapters = no breakers)
- **Bulkheads:** 0 registered
- **Overall health:** "healthy" (vacuously — nothing to break)

### Routing Layer
- **AdapterRegistry:** 0 adapters registered
- **ModeManager:** 7 venues configured (kalshi=sim, binance/coinbase/kraken/okx=sim, alpaca/ibkr=paper)
- **TradeRouter:** Cannot route — no adapters to route to

### Execution
- **Proposals generated:** 0
- **Orders routed:** 0
- **Fills:** 0

**Root Cause:** The `UnifiedVenueAdapter` implementations exist in `merid/pipeline/adapter.py` as an ABC, but no concrete adapters are instantiated and registered in `AdapterRegistry` at startup. The `trading/adapters/*.py` has concrete adapters (Alpaca, Coinbase, Kalshi, Paper) but these use a different interface (`trading.adapters.base`) and are not wired to the pipeline's `AdapterRegistry`.

---

## 7. UI & Telemetry Cross-Check

### UI Data Accuracy

| UI Component | Data Source | Accurate | Notes |
|---|---|---|---|
| Watchlist prices | `/api/prices/live` → CoinGecko | ✅ Real | BTC $68,976, ETH $2,053 |
| Portfolio equity | `/api/portfolio/summary` → Paper engine | ✅ Real | $93,200 equity |
| Agent count | `/api/agents/summary` → Manifest fallback | ⚠️ Stale | Shows 8 "active" but none are live |
| Trading summary | `/api/trading/summary` | ⚠️ Mixed | Shows 4 venues "connected" but no real connections |
| Risk exposure | `/api/risk/exposure` | ⚠️ Simulated | Values change on each call (random component) |
| Prediction markets | `/api/v1/prediction-markets/summary` | ❌ Empty | 0 markets, offline state |
| Venue health | `/api/v1/resilience/venues` | ❌ Empty | 0 venues tracked |

### Telemetry
- **Frontend → Backend telemetry:** 0 events received (sendBeacon likely blocked by Vite proxy)
- **Backend JSON logs:** Working (correlation_id middleware active)
- **Prometheus metrics:** Endpoint exists, counters at 0

---

## 8. Prioritized Issue List

| # | Component | Impact | Root Cause | Fix | Priority |
|---|---|---|---|---|---|
| **I-01** | Environment | All venues offline, no real trading possible | No `.env` file, all API keys `None` | Create `.env` with at least Kraken, Coinbase, Alpaca, Kalshi keys | **P0** |
| **I-02** | CCXT Price Feed | LivePriceFeed cache empty, paper engine gets no price updates | CCXT fetch_ticker fails silently (DEBUG-level logs); streaming task may not run | (a) Log first fetch error at WARNING; (b) Add `await asyncio.sleep(0)` after task creation; (c) Fix symbol format for public endpoints | **P0** |
| **I-03** | Pipeline Adapters | TradeRouter cannot route any orders | AdapterRegistry has 0 adapters; concrete adapters exist but aren't registered | Wire `trading/adapters/*.py` into `AdapterRegistry` at startup, or create bridge adapters | **P1** |
| **I-04** | Kalshi Markets | 0 prediction markets shown | No API key; mock fallback returns markets but aggregator doesn't store them | (a) Add Kalshi API key; (b) Fix mock→`_all_markets` storage path | **P1** |
| **I-05** | Agent Registry | Agents shown as "active" are manifest fallback, not live | `agents.registry` is empty; `AgentOrchestrator` uses different agent instances | Bridge orchestrator agents into the framework registry | **P2** |
| **I-06** | Trading Summary | Shows "4 venues connected" but none are real | `system_endpoints.py` and `real_data_endpoints.py` return simulated venue lists | Wire to actual adapter health checks | **P2** |
| **I-07** | Risk Exposure | Values have random component, not purely from paper engine | `real_data_endpoints.py` mixes real paper engine data with random offsets | Remove random component, use only paper engine data | **P2** |
| **I-08** | Telemetry | 0 frontend events reaching backend | Vite proxy may block sendBeacon; or telemetry disabled by default | Enable telemetry in frontend config; verify proxy forwards POST to `/api/v1/telemetry` | **P3** |
| **I-09** | CCXT Duplicate Streaming | `AgentOrchestrator.start()` also calls `price_feed.start_streaming()` (duplicate of main.py) | Two tasks competing for same singleton's streaming loop | Remove duplicate call from orchestrator or guard with `if not self.running` | **P3** |
| **I-10** | CoinGecko high/low | `high_24h` and `low_24h` are synthetic (±2%) | `/simple/price` endpoint doesn't include high/low | Switch to `/coins/markets` endpoint or remove synthetic values | **P3** |

---

## 9. Sanity Checks

### Verified ✅
- CoinGecko price feed (66 assets, real data)
- Paper trading engine (74 portfolios, position tracking)
- All REST API endpoints returning 200 (no 404/500)
- WebSocket endpoints (`/ws/trades`, `/ws/risk`) push real paper engine data
- Resilience layer (circuit breakers, bulkheads) — healthy (vacuously)
- Risk manager domain limits (prediction $5K, crypto $25K, equity $20K, macro $10K)
- Frontend polling and rendering of price data

### Unverified / Remaining ❓
- Actual CCXT exchange connectivity (requires API keys or DEBUG log analysis)
- Live order execution on any venue
- Agent consensus formation with real market data
- Kalshi market data with real API key
- Alpaca paper trading with real credentials
- WebSocket price streaming to `LivePriceStream.tsx` component
- Frontend telemetry round-trip
- Production deployment configuration

---

## 10. Recommended Next Steps (in order)

1. **Create `.env` file** with at least: `KRAKEN_API_KEY`, `COINBASE_API_KEY`, `ALPACA_API_KEY`/`ALPACA_API_SECRET`, `KALSHI_API_KEY_ID`
2. **Fix CCXT streaming** — set log level to WARNING for first fetch failure per symbol; add `await asyncio.sleep(0)` yield after task creation
3. **Register pipeline adapters** — bridge `trading/adapters/*.py` into `AdapterRegistry` at startup
4. **Fix Kalshi mock→aggregator** storage path so mock markets appear in `_all_markets`
5. **Bridge orchestrator agents** into framework registry for accurate UI reporting
6. **Remove random components** from risk/trading summary endpoints
7. **Enable frontend telemetry** and verify proxy forwarding
