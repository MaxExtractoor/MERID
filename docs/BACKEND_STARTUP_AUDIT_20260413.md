# Backend Startup Audit — 2026-04-13

Started with `MERID_PROFILE=kalshi-only`, `MERID_PM_TRADING_MODE=paper`, port 8011.

---

## CRITICAL — Runtime Errors

### 1. `TrackedPosition` has no attribute `size` (CRASH)
- **Severity**: CRITICAL — causes agent cycle failures (4/5 before pause)
- **File**: `merid/prediction/trading_agent.py` lines 1540, 1544
- **Log**: `Cycle error (4/5): 'TrackedPosition' object has no attribute 'size'`
- **Root cause**: BUG-009 FIX code references `pos.size` but `TrackedPosition` (in `merid/event_venues/kalshi/stop_loss.py:108`) uses `contracts`
- **Fix**: Change `pos.size` → `pos.contracts` on both lines

### 2. Fills ledger contaminated with 10,000 test fixtures
- **Severity**: CRITICAL — pollutes PnL, trade count, risk calculations
- **Evidence**: `/api/v1/kalshi/fills` returns fills with IDs like `fill_integrity_000`, `fill_a_001`, `fill_ghost_resolved_001`, `fill_immutable_001`, `fill_legit_001`
- **Source**: `data/kalshi_fills.db` — SQLite DB has test fixture data from prior test runs that was never cleaned
- **Impact**: `daily_trades: 10000` reported by risk endpoint, `daily_fees_usd: 33.62` from ghost fills, `realized_pnl_usd: -104.07` inflated
- **Fix**: Need a `MERID_FRESH_START` that purges the fills DB, or a migration that filters out non-venue fill IDs

### 3. Coinbase Advanced Trade API 401 Unauthorized
- **Severity**: HIGH — primary price feed unavailable, falls back to CCXT (0 exchanges configured)
- **Log**: `[AUTH-CONFIG-BUG] Coinbase v3 connection test failed with 401`
- **Impact**: `Price streaming started (CCXT fallback): 5 symbols, 0 exchanges` — no live spot prices flowing. Agents see stale/missing spot data
- **Note**: The API key may be a legacy/retail key rather than Advanced Trade API key

---

## HIGH — Hardcoded Values

### 4. `starting_balance` hardcoded to $10,000
- **File**: `web/api/kalshi_api.py:2077`
- **Code**: `starting_balance = getattr(ledger, "starting_balance", 10000.0)`
- **Issue**: If the ledger doesn't have a `starting_balance` attribute, it falls back to $10,000 — this silently produces wrong expected balance calculations

### 5. `open_market_count` hardcoded to 0
- **File**: `merid/event_venues/kalshi/kalshi_risk.py:1373`
- **Code**: `"open_market_count": 0,`
- **Issue**: The risk summary always reports 0 open markets regardless of actual state. This means the `max_open_markets: 20` limit is never enforced via this field

### 6. Risk API fallback defaults mask missing data
- **File**: `web/api/kalshi_api.py:3643-3646, 3729, 3733`
- **Values**: `max_notional_usd=10000`, `max_open_markets=20`, `max_drawdown_pct=10`
- **Issue**: When the risk engine fails to provide limits, these hardcoded fallbacks silently take over. Should log a warning when using defaults

### 7. `daily_loss_limit` defaults to 0
- **File**: `web/api/kalshi_api.py:3645`
- **Code**: `"daily_loss_limit": float(risk_summary.get("limits", {}).get("daily_loss_limit", 0))`
- **Issue**: Default of 0 means "no limit" — this is dangerous if the risk engine doesn't respond. Should default to a conservative value or raise an error

### 8. `_normalize_balance` heuristic is fragile
- **File**: `web/api/kalshi_api.py:288-295`
- **Code**: `if value > 10000 and value == int(value)` → treat as cents
- **Issue**: A $100.00 balance (10000 cents from Kalshi REST) gets divided by 100 → shows as $1.00. A $100.50 balance (10050 cents, which `== int(10050)` is True) also gets divided. But a $99.99 balance (9999 cents) passes through unchanged as $99.99 — which is correct by accident. The heuristic breaks when account balance is exactly $100-$100+ in whole dollars from the executor path

---

## MEDIUM — Security / Credentials in Logs

### 9. Redis credentials logged in plaintext
- **File**: `core/cache.py:34`
- **Log**: `Connected to Redis cache at redis://default:sqQo25jMxngDvAxQa1eqjFB7I9LHRkWz@redis-19394.c258.us-east-1-4.ec2.cloud.redislabs.com:19394/0`
- **Fix**: Mask password before logging: `REDIS_URL.replace(password, '***')`

### 10. Default email recipient is `admin@localhost`
- **File**: `notifications/notification_manager.py:255`
- **Code**: `return defaults.get("email", "admin@localhost")`
- **Issue**: Fallback email will silently swallow notification attempts. Should log a warning or raise

---

## MEDIUM — Recurring Warnings (Log Noise)

### 11. Neo4j connection retried every ~2 minutes
- **Log**: `Neo4j unavailable — using JSON-only memory storage: Couldn't connect to 127.0.0.1:7687`
- **Issue**: Repeated every ~2 min despite no Neo4j being present in Kalshi-only mode. Should be gated by `MERID_PROFILE=kalshi-only` or cached as "permanently unavailable" after first failure

### 12. Event-loop lag consistently 250-1900ms
- **Logs**: Constant stream of `Event-loop lag: XXXms` and `Event-loop lag elevated: XXXms (healthy<50ms)`
- **Worst**: `Event-loop lag degraded: 1906.0ms (degrade>=500ms)`
- **Root cause candidates**: 
  - News feed fetching (synchronous RSS parsing from CoinDesk/CoinTelegraph/Binance — uses `httpx.Client` not async `httpx.AsyncClient`)
  - Neo4j connection attempts (~3s timeout each)
  - `arb_scan` action: `Slow action 'arb_scan': 2203.5ms (budget 250ms)`

### 13. `Slow action 'arb_scan': 2203ms (budget 250ms)`
- **File**: `merid/loop.py` — `_run_arb_scan`
- **Issue**: The arb scanner is taking >2s despite being offloaded to thread pool. The 250ms budget is being exceeded by 9x

---

## LOW — Informational / Cosmetic

### 14. 44 agents started in paper mode — only ~10 are active crypto 15m
- **Log**: `[GRID-START] mode=paper live_enabled=False risk_halted=False agents=44`
- **Issue**: 44 agents running but most cycle with `hold_reason=no_edge` or `hold_reason=warmup`. Resource waste for unused agents

### 15. News monitor generates 0 MarketOpinions from all articles
- **Log**: `News ANALYZE complete: 0 MarketOpinions generated` (repeated for every article)
- **Issue**: Every fetched article is analyzed then "rejected by simulation" — the news→opinion pipeline appears to never produce actionable output

### 16. `KALSHI_ENV=live` while in paper mode
- **Log**: `KALSHI_ENV=live but portfolio mode is not fully live`
- **Issue**: Startup validation correctly warns, but the Kalshi client is authenticating against the LIVE environment even in paper mode. This means paper-mode agents are reading live orderbooks and positions (which is fine for data, but confusing for operators)

### 17. Fills poller reconciliation discrepancy
- **Log**: `Using 15 computed positions from fills (REST returned empty)` then `Position cache synced from REST: 0 positions` then `Position cache synced from reconciliation: 15 positions`
- **Issue**: REST API says 0 positions, but fills-based computation says 15. Likely stale fills in DB creating phantom positions

### 18. `event-loop mismatch` retry
- **Log**: `[kalshi] get_market(KXXRP15M-...) event-loop mismatch (Event loop is closed), HTTP client reset; retry 1/4`
- **Issue**: The Kalshi HTTP client's event loop is getting closed/reset during concurrent operations. Self-heals via retry but indicates a shared client lifecycle issue

---

## Summary Table

| # | Severity | Type | File | Issue |
|---|----------|------|------|-------|
| 1 | CRITICAL | Bug | trading_agent.py:1540 | `TrackedPosition.size` → should be `.contracts` |
| 2 | CRITICAL | Data | data/kalshi_fills.db | 10K test fixture fills polluting ledger |
| 3 | HIGH | Config | live_price_feed.py | Coinbase 401 — no live spot prices |
| 4 | HIGH | Hardcode | kalshi_api.py:2077 | `starting_balance = 10000.0` fallback |
| 5 | HIGH | Hardcode | kalshi_risk.py:1373 | `open_market_count: 0` always |
| 6 | MEDIUM | Hardcode | kalshi_api.py:3643+ | Risk limit fallback defaults (10000/20/10) |
| 7 | MEDIUM | Hardcode | kalshi_api.py:3645 | `daily_loss_limit` defaults to 0 (no limit) |
| 8 | MEDIUM | Bug | kalshi_api.py:288 | `_normalize_balance` heuristic fragile |
| 9 | MEDIUM | Security | core/cache.py:34 | Redis password logged in plaintext |
| 10 | MEDIUM | Hardcode | notification_manager.py:255 | `admin@localhost` fallback email |
| 11 | MEDIUM | Noise | neo4j_graph.py | Neo4j retry every 2min in kalshi-only mode |
| 12 | MEDIUM | Perf | ws/loop | Event-loop lag 250-1900ms constant |
| 13 | MEDIUM | Perf | loop.py | arb_scan 2200ms on 250ms budget |
| 14 | LOW | Waste | pm_runtime | 44 agents, ~34 idle |
| 15 | LOW | Dead path | news_monitor_agent | 0 MarketOpinions from all articles |
| 16 | LOW | Config | startup_validations | KALSHI_ENV=live in paper mode |
| 17 | LOW | Data | fills_poller | 15 phantom positions from stale fills |
| 18 | LOW | Bug | kalshi/client.py | Event-loop mismatch retries |
