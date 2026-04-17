---
title: KalshiContinuousTrader as scanner-only (no execution)
date: 2026-03-26
status: draft
---

## Goal

Convert `KalshiContinuousTrader` (CT) into a **scanner/metrics producer only**. CT must **never place, cancel, or modify orders** and must **never call Kalshi REST**. All live orders must flow through the unified path:

`AgentGrid` → `KalshiTradingAgent` → `merid.event_venues.kalshi.order_router.route_order_async()`.

## Non-goals

- Rewriting the unified execution path, consensus, or sizing engines.
- Changing trading strategy logic inside `KalshiTradingAgent`.
- Introducing a new live execution path for CT.

## Current state (evidence)

- CT is started in `web/main.py` and currently performs:
  - spot proxy fetch (CoinGecko/Coinbase/Binance)
  - Kalshi REST calls for `/markets`, `/markets/{ticker}/orderbook`, `/portfolio/*`
  - direct REST order placement/cancel to `/portfolio/orders`
- The unified execution path already exists and enforces shared safety:
  - `order_router.route_order_async()` performs live execution gate checks
  - `ExecutionGuard` applies kill switches, CQI throttles, caps, and promotion checks
  - reconciliation can block execution on critical discrepancies

## Design

### Behavioral contract

CT must:

- **Never submit orders** (buy/sell), never cancel orders, never auto-exit.
- **Never call Kalshi REST** endpoints.
- Continue to:
  - compute and publish cycle metrics (spot, vol proxy, fee-drag windowing, candidate counts)
  - produce **ranked market candidates** (ticker, side, implied price, estimated edge/confidence inputs)
  - expose a stable `status_snapshot()` for API/UI use.

### Data sources

CT will derive candidates only from in-process/shared stores:

- **Market universe**: `KalshiMarketCatalog.snapshot()` (already maintained elsewhere).
- **Top-of-book / microstructure**: `KalshiMarketStateStore` (WS-derived book state).
- **Spot proxy**: existing CoinGecko/Coinbase/Binance spot fetch remains allowed (non-Kalshi).
- **Indicators**: existing per-asset indicator stacks already embedded in CT.

If market catalog/state is unavailable, CT degrades gracefully:

- emits metrics indicating missing inputs
- publishes an empty candidate set
- continues running (no crash), preserving observability

### Outputs

- `KalshiContinuousTrader.status_snapshot()` includes:
  - cycle + spot metadata
  - vol regime metrics
  - per-asset indicator freshness
  - **`last_candidates`**: top-N ranked candidates with fields required for downstream consumers
- CT publishes an event on the core event bus each cycle:
  - topic: `kalshi:ct_scan`
  - payload: `{cycle, ts, spots, candidates, diagnostics}`

### Safety properties

- “Scanner-only” is enforced by code structure (no calls to order placement/cancel functions in the cycle) and by a hard guard:
  - an explicit `scanner_only=True` mode that causes any attempt to call REST helpers to raise/log and return.

## Implementation outline (targeted changes)

- Update `merid/trading/kalshi_continuous_trader.py`:
  - add `scanner_only` to `TraderConfig` (default true)
  - remove dependency on RSA credentials for operation
  - replace Kalshi REST market/orderbook/portfolio calls with:
    - catalog snapshot iteration
    - market state lookup for bid/ask/spread/oi/expiry
  - compute edge for candidates and publish ranked list
  - ensure no `requests` calls are made to Kalshi URLs

## Testing / verification

- Unit: add/extend tests ensuring CT does not call REST and produces candidates from catalog/state when present.
- Integration: run existing Kalshi hardening tests and verify no new lints.

