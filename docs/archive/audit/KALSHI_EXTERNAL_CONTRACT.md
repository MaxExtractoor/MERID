# Kalshi External Contract

**SPEC_VERSION:** 1.0.0  
**Last Updated:** 2026-05-16  
**Kalshi API Version:** v1 (https://api.kalshi.co/v1)  
**Status:** Active - 15-minute crypto markets only

---

## Overview

This document enumerates the external contract between MERID and Kalshi's API. It serves as a single source of truth for:
- API endpoints used by MERID
- Supported market tickers and series
- Ticker naming conventions
- Rate limits and quotas
- Breaking changes to monitor

**Purpose:** Lock the external contract to prevent silent API drift from breaking reconciliation or trading logic.

---

## Supported Universe

### 15-Minute Crypto Markets

MERID trades exclusively on Kalshi's 15-minute crypto prediction markets. The universe is pinned to:

| Asset | Base Ticker | 15M Series Ticker | Market ID Pattern |
|-------|-------------|------------------|-------------------|
| BTC   | KXBTC       | KXBTC15M         | KXBTC15M-*        |
| ETH   | KXETH       | KXETH15M         | KXETH15M-*        |
| SOL   | KXSOL       | KXSOL15M         | KXSOL15M-*        |
| XRP   | KXXRP       | KXXRP15M         | KXXRP15M-*        |
| DOGE  | KXDOGE      | KXDOGE15M        | KXDOGE15M-*       |

**Total Markets:** ~5 assets × 15-minute windows = ~75 active markets at any time

### Series Ticker Convention

Kalshi series tickers follow this pattern:
```
KX{ASSET}{TIMEFRAME}
```

Where:
- `ASSET`: BTC, ETH, SOL, XRP, DOGE
- `TIMEFRAME`: 15M (15-minute), H1 (hourly), D1 (daily), W1 (weekly), Y (annual)

**MERID Pin:** Only `KX{ASSET}15M` tickers are used for 15-minute crypto trading.

### Market ID Convention

Market IDs follow the pattern:
```
KX{ASSET}{TIMEFRAME}-{YYYYMMDD}-{HHMM}-{SIDE}
```

Example:
- `KXBTC15M-20260516-1430-YES` - BTC 15-minute market for 2:30 PM UTC on 2026-05-16, YES side
- `KXBTC15M-20260516-1430-NO` - Same market, NO side

**MERID Pin:** All market IDs start with `KX{ASSET}15M-`.

---

## API Endpoints Used

### Market Discovery

| Endpoint | Method | Purpose | Frequency |
|----------|--------|---------|-----------|
| `/markets` | GET | List all markets | Every catalog refresh (1-5 min) |
| `/markets?series_ticker=KX{ASSET}15M` | GET | Filter by 15-minute series | Every catalog refresh |

**Response Fields Used:**
- `market_id` - Unique market identifier
- `series_ticker` - Series ticker (e.g., KXBTC15M)
- `ticker_name` - Human-readable name
- `close_time` - Market close timestamp
- `status` - Active, closed, etc.
- `yes_price`, `no_price` - Current prices
- `volume` - Trading volume

### Portfolio & Positions

| Endpoint | Method | Purpose | Frequency |
|----------|--------|---------|-----------|
| `/portfolio/balance` | GET | Account balance | Reconciliation (every 5-10 min) |
| `/portfolio/positions` | GET | Current positions | Reconciliation (every 5-10 min) |
| `/portfolio/fills` | GET | Trade fills | Reconciliation (every 5-10 min) |

**Response Fields Used:**
- `total_balance` - Account balance in cents
- `positions[].market_id` - Market ID
- `positions[].yes_qty`, `positions[].no_qty` - Position quantities
- `fills[].trade_id` - Unique trade ID
- `fills[].market_id` - Market ID
- `fills[].side` - YES or NO
- `fills[].count` - Quantity
- `fills[].price` - Price in cents
- `fills[].created_at` - Trade timestamp

### Trading

| Endpoint | Method | Purpose | Frequency |
|----------|--------|---------|-----------|
| `/trade/order` | POST | Place market order | On signal |
| `/trade/cancel` | POST | Cancel order | On signal |

**Request Fields Used:**
- `market_id` - Market to trade
- `side` - YES or NO
- `count` - Quantity (number of contracts)
- `price` - Price in cents (for limit orders)

**Response Fields Used:**
- `order_id` - Unique order ID
- `status` - OPEN, FILLED, CANCELED
- `filled_qty` - Quantity filled

### WebSocket

| Channel | Purpose | Connection Type |
|---------|---------|-----------------|
| `/ws/feed` | Real-time orderbook updates | Persistent |
| `/ws/trade_updates` | Fill notifications | Persistent |

**Message Types:**
- `orderbook` - Orderbook snapshot
- `trade` - Trade notification
- `fill` - Fill notification (used for position cache)

---

## Rate Limits

### Current Quotas (as of 2026-05-16)

| Endpoint | Rate Limit | Burst | MERID Usage |
|----------|------------|-------|-------------|
| `/markets` | 60 req/min | 10 | ~12 req/min (catalog refresh) |
| `/portfolio/*` | 120 req/min | 20 | ~12 req/min (reconciliation) |
| `/trade/*` | 60 req/min | 10 | ~5 req/min (trading) |
| WebSocket | 50 msg/sec | 100 | ~10 msg/sec (orderbook + fills) |

**Total API Budget:** ~240 req/min, 50 msg/sec WebSocket

### MERID Rate Limit Budget

| Subsystem | Budget | Actual | Headroom |
|-----------|--------|--------|----------|
| Market Catalog | 12 req/min | 12 req/min | 0% |
| Reconciliation | 12 req/min | 12 req/min | 0% |
| Trading | 5 req/min | 5 req/min | 83% |
| WebSocket | 10 msg/sec | 10 msg/sec | 80% |

**Note:** Budget assumes 5-minute reconciliation interval. 10-minute interval would double headroom.

---

## Unit Conventions

### Currency

Kalshi uses **cents** for all monetary values:
- Prices: 50 cents = $0.50
- Balances: 10000 cents = $100.00
- Notional: qty × price (in cents)

**MERID Handling:**
- `KalshiFill` stores prices/fees in cents
- `KalshiClient` converts dollars to cents for API calls
- `KalshiClient` converts cents to dollars for internal use

### Quantities

- **Contracts:** Integer count (e.g., 10 contracts)
- **No fractional contracts** in Kalshi
- Position quantities are integers

### Timestamps

Kalshi uses **Unix timestamps in seconds**:
- `close_time` - Unix epoch seconds
- `created_at` - Unix epoch seconds

**MERID Handling:** Convert to UTC datetime objects for internal use.

---

## Breaking Changes to Monitor

### High Priority (BLOCKS TRADING)

1. **Series Ticker Format Change**
   - Current: `KX{ASSET}15M`
   - Risk: Catalog discovery fails
   - Detection: E2E tests fail, catalog refresh returns empty
   - Action: Update `kalshi_agent_grid_catalog_series_tickers()`

2. **Market ID Format Change**
   - Current: `KX{ASSET}15M-{YYYYMMDD}-{HHMM}-{SIDE}`
   - Risk: Order routing fails, reconciliation breaks
   - Detection: Trade orders rejected, fills not matched
   - Action: Update market ID regex in `market_catalog.py`

3. **Price Unit Change**
   - Current: Cents
   - Risk: Wrong order sizes, PnL errors
   - Detection: Orders rejected for invalid price, reconciliation discrepancies
   - Action: Update unit conversion in `KalshiClient`

4. **WebSocket Message Format Change**
   - Current: JSON with specific fields
   - Risk: Position cache desyncs
   - Detection: WebSocket parse errors, cache not updating
   - Action: Update `KalshiWebSocketBridge` message handlers

### Medium Priority (DEGRADES OBSERVABILITY)

1. **Pagination Cursor Change**
   - Current: `next_cursor` string
   - Risk: Incomplete fills/positions data
   - Detection: Missing fills in ledger, reconciliation drift
   - Action: Update pagination logic in `KalshiClient`

2. **Rate Limit Change**
   - Current: 240 req/min budget
   - Risk: 429 errors, throttling
   - Detection: Increased rate limit errors in logs
   - Action: Adjust reconciliation interval, add backoff

3. **Field Deprecation**
   - Risk: Missing data in reconciliation
   - Detection: KeyError in fill/position parsing
   - Action: Update field names in `KalshiClient` models

### Low Priority (UI/LOGGING)

1. **Human-Readable Field Changes**
   - Risk: Confusing logs, UI display issues
   - Detection: Log warnings, UI anomalies
   - Action: Update logging/display logic

---

## Monitoring & Detection

### Automated Detection

1. **E2E Test Suite**
   - `tests/event_venues/kalshi/test_btc_15m_reconciliation_e2e.py`
   - Tests all 5 assets with real API patterns
   - Fails on API contract changes

2. **Live Drift Monitor**
   - `scripts/kalshi_live_drift_monitor.py`
   - Runs every 10 minutes in production
   - Alerts on reconciliation drift (API change indicator)

3. **Catalog Refresh Health**
   - Log: `[CATALOG-REFRESH-ENTRY]` with market count
   - Alert if market count drops unexpectedly

### Manual Detection

1. **Kalshi Changelog**
   - https://news.kalshi.com
   - Review weekly for breaking changes

2. **Kalshi Status**
   - https://status.kalshi.com
   - Monitor for API incidents

3. **API Docs**
   - https://docs.kalshi.com
   - Review monthly for endpoint changes

---

## Version History

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | 2026-05-16 | Initial contract definition - 15-minute crypto only |

---

## Related Documentation

- **Reconciliation Audit:** `docs/audit/KALSHI_RECONCILIATION_AUDIT.md`
- **Runbook:** See "When Kalshi Reconciliation Breaks" section above
- **E2E Tests:** `tests/event_venues/kalshi/test_btc_15m_reconciliation_e2e.py`
- **Drift Monitor:** `scripts/kalshi_live_drift_monitor.py`
- **Kalshi API Docs:** https://docs.kalshi.com

---

## Contract Violation Procedure

If you suspect a contract violation:

1. **Check E2E tests:** Run `pytest tests/event_venues/kalshi/test_btc_15m_reconciliation_e2e.py`
2. **Check drift monitor:** Review recent drift monitor runs
3. **Check Kalshi status:** https://status.kalshi.com
4. **Check Kalshi changelog:** https://news.kalshi.com
5. **Consult runbook:** See "When Kalshi Reconciliation Breaks" section
6. **Update this document:** If contract changed, version bump and document changes
