# Kalshi Integration Map — MERID Audit

**Generated:** 2026-03-28  
**Scope:** Complete inventory of all Kalshi touchpoints in the live MERID repo  
**Classification:** Internal audit document for architecture verification

---

## 1. Where Kalshi Lives in MERID — Overview

Kalshi is the **primary and default venue** for MERID's prediction market trading. The integration spans:

- **Event Venue Layer:** `merid/event_venues/kalshi/` — canonical REST/WebSocket clients, market catalog, fills ledger
- **Trading Layer:** `merid/trading/kalshi_*.py` — continuous trader, filter pipeline
- **Risk Layer:** `merid/event_venues/kalshi/kalshi_risk.py` — venue-specific risk checks
- **API Layer:** `web/api/kalshi*.py` — 15+ API modules exposing Kalshi endpoints
- **Settlement/RTI:** `merid/event_venues/kalshi/cfb_settlement.py` — CF Benchmarks integration
- **UI Layer:** `web/react/src/views/Kalshi*.tsx` — 8 canonical Kalshi views

### Kalshi-Only Mode Architecture

The system operates in **Kalshi-only mode by default** (`settings.KALSHI_ONLY = True`). This:
- Restricts UI to 8 canonical Kalshi views (Dashboard, Grid, Portfolio, Terminal, Vol Dashboard, Risk, Agent Performance, Operator)
- Gates all trading through Kalshi venue adapters
- Disables Polymarket and other legacy venues (moved to `_legacy/`)

---

## 2. Integration Points Table

| File | Role | Key Classes/Functions | Upstream Callers | Downstream Dependents |
|------|------|----------------------|------------------|----------------------|
| `merid/event_venues/kalshi/client.py` | **Auth + REST client** | `KalshiVenueClient`, `_sign_headers()`, `_authenticate_rsa()`, `place_order_result()`, `get_orderbook_result()` | `kalshi_api.py`, `order_router.py`, `fills_poller.py`, `trading_agent.py` | All order placement, market data, balance queries |
| `merid/event_venues/kalshi/models.py` | **DTOs + config** | `KalshiConfig`, `KalshiMarket`, `KalshiOrder`, `KalshiFill`, `KalshiPosition` | `client.py`, `ws.py`, `market_catalog.py` | All Kalshi data handling |
| `merid/event_venues/kalshi/ws.py` | **WebSocket transport** | `KalshiWebSocket`, `connect()`, `subscribe_orderbook()`, `subscribe_trades()`, `_handle_message()` | `ws_bridge.py`, `main.py` lifespan | `market_state.py`, sentiment pipelines |
| `merid/event_venues/kalshi/ws_bridge.py` | **WS → internal bus** | `KalshiWSBridge`, `start()`, `subscribe_ticker()`, `apply_orderbook_message()` | `main.py` lifespan | `MarketStateStore`, lanes, trading agents |
| `merid/event_venues/kalshi/market_catalog.py` | **Market discovery** | `KalshiMarketCatalog`, `refresh()`, `get_markets_by_asset()`, `_detect_from_ticker()` | `main.py` lifespan, `KalshiContinuousTrader` | Agent market resolution, UI market lists |
| `merid/event_venues/kalshi/market_state.py` | **Live state cache** | `KalshiMarketStateStore`, `apply_quote()`, `apply_orderbook_message()`, `get_state()` | `ws_bridge.py`, `market_catalog.py` | `order_router.py`, `kalshi_api.py` fast-path |
| `merid/event_venues/kalshi/fills_ledger.py` | **Canonical fills ledger** | `KalshiFillsLedger`, `ingest_http_fills()`, `ingest_ws_fill()`, `reconcile_with_kalshi_positions()` | `fills_poller.py`, `ws_bridge.py` | `kalshi_api.py`, PnL calculations, position tracking |
| `merid/event_venues/kalshi/fills_poller.py` | **HTTP fills ingestion** | `FillsPoller`, `poll_loop()`, `get_kalshi_fills()` | `main.py` lifespan | `fills_ledger.py` |
| `merid/event_venues/kalshi/order_router.py` | **Order dispatch** | `route_order()`, `OrderIntent`, `OrderResult`, `handle_order_group_triggered()` | `trading_agent.py`, `KalshiContinuousTrader` | `client.py`, risk checks |
| `merid/event_venues/kalshi/kalshi_risk.py` | **Venue risk checks** | `KalshiRiskEngine`, `check_order()`, `check_portfolio_exposure()` | `order_router.py`, `kalshi_api.py` | Position limits, exposure tracking |
| `merid/event_venues/kalshi/cfb_settlement.py` | **CF Benchmarks RTI** | `CFBSettlementParams`, `get_settlement_params()`, `is_rti_settlement_type()` | `settlement_execution_guard.py`, market filters | Expiry gating, settlement validation |
| `merid/event_venues/kalshi/settlement_execution_guard.py` | **RTI trade gating** | `check_settlement_grade()`, `allow_trade_if_incomplete()` | `order_router.py` | Trade blocking near expiry |
| `merid/event_venues/kalshi/market_selector.py` | **Agent → series mapping** | `AGENT_SERIES_MAP`, `resolve_series_ticker()`, `get_agent_market_tickers()` | `agent_grid.py` | Agent market resolution |
| `merid/trading/kalshi_continuous_trader.py` | **CT trading loop** | `KalshiContinuousTrader`, `run()`, `scan_and_trade()`, `_calculate_order_size()` | `main.py` lifespan | `order_router.py`, `client.py` |
| `merid/trading/kalshi_filter_pipeline.py` | **Market filtering** | `FilterPipeline`, `apply()`, `Filters` | `KalshiContinuousTrader` | Market eligibility |
| `merid/prediction/trading_agent.py` | **Agent signal→orders** | `KalshiTradingAgent`, `_execute_signal()`, `_submit_to_consensus()` | `agent_grid.py`, `consensus_aggregator.py` | `order_router.py` |
| `web/api/kalshi_api.py` | **Core Kalshi API** | `GET /markets`, `POST /orders`, `GET /positions`, `GET /fills`, `_get_client()` singleton | Frontend views | All Kalshi data endpoints |
| `web/api/kalshi_grid_api.py` | **Agent grid API** | `GET /kalshi-grid/agents`, `POST /kalshi-grid/mode`, `POST /canary-trade` | `KalshiGridView.tsx` | Agent orchestration |
| `web/api/kalshi_continuous_trader_api.py` | **CT API** | `GET /continuous-trader/status`, `POST /continuous-trader/stop` | `KalshiBankrollPanel.tsx` | Continuous trader control |
| `web/api/rti_feed_api.py` | **RTI feed API** | `GET /rti-feed/status`, `GET /rti-feed/buffer/{asset}` | Frontend risk views | CFB RTI buffer status |
| `web/main.py` | **Lifespan orchestration** | `lifespan()`, Kalshi client singleton init, WS bridge startup | FastAPI | All Kalshi services |
| `merid/settings.py` | **Configuration** | `Settings.KALSHI_ONLY`, `KALSHI_USE_DEMO`, `KALSHI_API_KEY_ID`, `KALSHI_PRIVATE_KEY_PATH` | All Kalshi modules | Environment-dependent behavior |

---

## 3. Kalshi-Specific Constants / Env Vars

### Environment Variables (via `merid/settings.py`)

| Variable | Default | Description | Authority |
|----------|---------|-------------|-----------|
| `KALSHI_API_KEY_ID` | `None` | RSA key ID from Kalshi dashboard | Single source |
| `KALSHI_PRIVATE_KEY_PATH` | `None` | Path to `.pem` private key file | Single source |
| `KALSHI_PRIVATE_KEY_PEM` | `None` | Inline PEM string (alternative) | Single source |
| `KALSHI_API_HOST` | `None` | Override URL (rarely used) | Single source |
| `KALSHI_USE_DEMO` | `True` | Demo vs live API toggle | Single source |
| `KALSHI_ONLY` | `True` | Kalshi-only mode flag | Single source |
| `MERID_PM_TRADING_MODE` | `"paper"` | Paper/live mode | Single source |
| `MERID_PM_LIVE_ENABLED` | `False` | Explicit live unlock | Single source |
| `KALSHI_PORTFOLIO_BANKROLL_CENTS` | `50_000_00` | Risk bankroll base | Single source |

### API Base URLs (from `merid/event_venues/kalshi/models.py`)

```python
# Production (live)
rest_api_url: str = "https://api.elections.kalshi.com/trade-api/v2"
ws_api_url: str = "wss://api.elections.kalshi.com/trade-api/ws/v2"

# Demo/sandbox
demo_rest_api_url: str = "https://demo-api.kalshi.co/trade-api/v2"
demo_ws_api_url: str = "wss://demo-api.kalshi.co/trade-api/ws/v2"
```

**Authority:** `KalshiConfig` class in `models.py` is the single source of truth. `client.py` and `ws.py` both derive URLs from this config.

### Hardcoded Duplicate Check

| Location | Value | Status |
|----------|-------|--------|
| `merid/event_venues/kalshi/client.py:515` | `full_path = f"/trade-api/v2{path}"` | ✅ Required for signing |
| `merid/event_venues/kalshi/ws.py:129` | `path = "/trade-api/ws/v2"` | ✅ WebSocket endpoint |
| `merid/event_venues/kalshi/models.py:129-132` | Canonical URLs | ✅ Source of truth |

**No problematic hardcoded duplicates found.** All path construction uses the `/trade-api/v2` prefix consistently.

---

## 4. Kalshi-Only Mode Switch

### Detection Logic

```python
# merid/settings.py
KALSHI_ONLY: bool = Field(default=True, description="Kalshi-only mode: restricts UI/API to 8 canonical Kalshi views")

# Access pattern
from merid.settings import settings
if settings.KALSHI_ONLY:
    # restrict to Kalshi views
```

### Conditional Behaviors Using KALSHI_ONLY

| Location | Conditional | Behavior Change |
|----------|-------------|-----------------|
| `web/main.py` (implied) | `settings.KALSHI_ONLY` | Only registers Kalshi routers |
| `merid/event_venues/__init__.py` | `KALSHI_ONLY` | Only exports Kalshi venue |
| `web/react/src/config/views.ts` | `kalshiOnly` filter | Restricts sidebar to 8 views |
| `merid/venue_registry.py` | Documented Kalshi-only | Polymarket moved to `_legacy/` |

### Safety Consistency Check

| Check | Status | Notes |
|-------|--------|-------|
| CF RTI gating skipped in live? | ❌ NOT FOUND | Settlement guard always active |
| Bypass for shadow/dry-run? | ⚠️ Requires explicit env | `KALSHI_CT_BYPASS_PM_LIVE_GATE` exists in CT only |
| Demo→Live switch safety? | ✅ Guarded | `MERID_PM_LIVE_ENABLED` required |

---

## 5. Auth and Transport Verification

### HTTP Signing Implementation (`client.py:414-447`)

```python
def _sign_headers(self, method: str, path: str) -> Dict[str, str]:
    """Generate Kalshi RSA auth headers."""
    ts_ms = str(int(time.time() * 1000))
    message = ts_ms + method.upper() + path  # e.g., "1743140000000GET/trade-api/v2/portfolio/orders"
    signature = self._private_key.sign(
        message.encode(),
        padding.PSS(
            mgf=padding.MGF1(hashes.SHA256()),
            salt_length=padding.PSS.DIGEST_LENGTH,
        ),
        hashes.SHA256(),
    )
    return {
        "KALSHI-ACCESS-KEY": self.config.api_key,
        "KALSHI-ACCESS-TIMESTAMP": ts_ms,
        "KALSHI-ACCESS-SIGNATURE": base64.b64encode(signature).decode(),
    }
```

**Verification against Kalshi docs:**
- ✅ Timestamp in milliseconds
- ✅ Method uppercase
- ✅ Path includes `/trade-api/v2` prefix
- ✅ PSS padding with SHA-256
- ✅ `salt_length=DIGEST_LENGTH`
- ✅ Headers match: `KALSHI-ACCESS-KEY`, `KALSHI-ACCESS-TIMESTAMP`, `KALSHI-ACCESS-SIGNATURE`

### Environment Routing

```python
# client.py:274-276
_env = "demo" if self.config.use_demo else "live"

# models.py:129-132 + 146-150
rest_api_url = "https://api.elections.kalshi.com/trade-api/v2"  # live
demo_rest_api_url = "https://demo-api.kalshi.co/trade-api/v2"  # demo
```

**Demo vs Live selection:**
- ✅ Exclusive via `KALSHI_USE_DEMO` env var
- ✅ Circuit breaker namespaced by env (`kalshi_demo` vs `kalshi_live`)
- ✅ No accidental switching logic found

### Live Trading Guards

```python
# merid/settings.py:408-410
if self.MERID_TRADING_MODE.lower() == "live":
    if not self.MERID_LIVE_TRADING_UNLOCKED:
        issues.append("Live trading requires MERID_LIVE_TRADING_UNLOCKED=true")
```

**Additional guards:**
- `MERID_PM_LIVE_ENABLED` required for prediction market live mode
- `KALSHI_CT_BYPASS_PM_LIVE_GATE` (CT-specific) requires explicit opt-in

### WebSocket Transport

| Feature | Implementation | Status |
|---------|---------------|--------|
| Reconnect/backoff | `ws.py:51-52`, exponential up to 60s | ✅ |
| Resubscribe on reconnect | `ws.py:reconnect()` replays subscriptions | ✅ |
| Sequence tracking | `ws.py:63-64` `_last_seq`, `_seq_gaps` | ✅ |
| Error message handling | `ws.py:28-36` error code classification | ✅ |
| Async message queue | `ws.py:67` `asyncio.Queue(maxsize=4096)` | ✅ |
| Ping/pong | `ws.py` automatic via websockets lib | ✅ |

---

## 6. Symbol and Market Catalog

### Supported Crypto Assets

From `market_catalog.py:54-66` and `cfb_settlement.py:43-58`:
- **BTC** — KXBTC, KXBITCOIN series
- **ETH** — KXETH, KXETHEREUM series
- **SOL** — KXSOL, KXSOLANA series
- **XRP** — KXXRP, KXRIPPLE series
- **DOGE** — KXDOGE, KXDOGECOIN series

### Timeframe Suffix Mapping

From `market_selector.py`:
- `15m` → `-15M` suffix
- `1h`/`hourly` → no suffix (base series)
- `daily` → `-D` suffix
- `weekly` → `-W` suffix

### Ticker Normalization

```python
# market_filter.py (canonical helpers)
group_id_from_ticker(ticker: str) -> str
extract_asset_from_ticker(ticker: str) -> str
_normalize_timeframe(timeframe: str) -> str
```

**Single source:** All ticker parsing routes through `market_filter.py` functions.

---

## 7. Legacy Perp Contamination Check

| Pattern | Found In | Status |
|---------|----------|--------|
| `binance` | `merid/event_venues/_legacy/`, `config/` (inactive) | ✅ Archived |
| `perp` | `merid/strategies/` (some backtest files) | ✅ Not in hot path |
| `funding` | Archived modules | ✅ Not active |
| `mark_price` | Not found in Kalshi code | ✅ Clean |

**Assessment:** No legacy perp assumptions contaminate Kalshi code paths. All sizing uses Kalshi-specific cents/percentage logic.

---

## 8. Files by Classification

### Auth
- `merid/event_venues/kalshi/client.py` — RSA signing, auth
- `merid/event_venues/kalshi/models.py` — Config DTOs
- `merid/event_venues/kalshi/ws.py` — WS auth

### Market Data
- `merid/event_venues/kalshi/client.py` — REST market data
- `merid/event_venues/kalshi/ws.py` — WebSocket streaming
- `merid/event_venues/kalshi/ws_bridge.py` — Bridge to internal bus
- `merid/event_venues/kalshi/market_catalog.py` — Discovery + categorization
- `merid/event_venues/kalshi/market_state.py` — Live state cache

### Orders
- `merid/event_venues/kalshi/client.py` — Order placement/cancel
- `merid/event_venues/kalshi/order_router.py` — Intent routing
- `merid/event_venues/kalshi/order_manager.py` — Order lifecycle
- `merid/event_venues/kalshi/order_group_manager.py` — Bracket orders

### Fills/Positions
- `merid/event_venues/kalshi/fills_ledger.py` — Canonical ledger
- `merid/event_venues/kalshi/fills_poller.py` — HTTP ingestion
- `merid/event_venues/kalshi/position_cache.py` — Position tracking

### Risk
- `merid/event_venues/kalshi/kalshi_risk.py` — Venue risk engine
- `merid/event_venues/kalshi/bracket_risk.py` — Bracket order risk
- `merid/event_venues/kalshi/btc15m_risk.py` — BTC-specific risk

### RTI/CFB Settlement
- `merid/event_venues/kalshi/cfb_settlement.py` — Settlement parameters
- `merid/event_venues/kalshi/settlement_execution_guard.py` — Trade gating
- `merid/event_venues/kalshi/settlement_poller.py` — Settlement monitoring

### Trader/Agents
- `merid/trading/kalshi_continuous_trader.py` — CT trading loop
- `merid/prediction/trading_agent.py` — Agent signal execution
- `merid/event_venues/kalshi/auto_promoter.py` — Agent promotion

### UI/API Adapters
- `web/api/kalshi_api.py` — Core REST API
- `web/api/kalshi_grid_api.py` — Agent grid
- `web/api/kalshi_continuous_trader_api.py` — CT control
- `web/api/rti_feed_api.py` — RTI status

---

## 9. Summary

**Kalshi integration status:** Comprehensive and production-ready.

**Key architectural strengths:**
1. **Single-source URL config** — `KalshiConfig` in `models.py`
2. **Dual-ingestion fills ledger** — HTTP poller + WebSocket with reconciliation
3. **Circuit breaker per env** — `kalshi_demo` vs `kalshi_live` isolation
4. **RSA signing per-request** — Timestamp + method + path, PSS/SHA256
5. **CFB settlement integration** — RTI-based gating for crypto contracts
6. **Kalshi-only mode** — Clean separation from legacy venues

**Areas requiring ongoing vigilance:**
1. **Fills reconciliation** — Must run periodically to detect drift
2. **RTI buffer completeness** — Strict mode should block trades in final minute if incomplete
3. **Live mode guards** — Multiple interlocks exist; verify no bypass paths emerge

---

*Document version: 1.0*  
*Next review: After any Kalshi API version change or major refactors*
