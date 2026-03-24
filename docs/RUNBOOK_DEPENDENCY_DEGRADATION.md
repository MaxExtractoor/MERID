# Runbook: Dependency Degradation (Kalshi)

## When you see the banner
- Message: `Dependencies degraded: kalshi_websocket, market_catalog`
- Impact: real-time Kalshi data or catalog discovery is stale; trading signals may pause.

## What to check
- Call `GET /api/v1/dependencies/health`
  - `overall_status`: `healthy` | `degraded` | `down` | `disabled`
  - `dependencies.kalshi_websocket`
    - `status`, `last_msg_ago_s`, `messages_received`, `reconnect_count`
  - `dependencies.market_catalog`
    - `status`, `market_count`, `last_refresh`, `age_s`
- System rollup: `/api/system/health` and `/api/v1/system/health` include the dependency snapshot and set `incident_flag` when degraded/down.

## Thresholds (env-tunable)
- WebSocket stale → degraded if no messages for >90s, down if >240s.
  - Override with `MERID_KALSHI_WS_STALE_DEGRADED_S` / `MERID_KALSHI_WS_STALE_DOWN_S`.
- Catalog stale → degraded if >900s since refresh, down if >1800s, or degraded if `market_count==0`.
  - Override with `MERID_MARKET_CATALOG_STALE_DEGRADED_S` / `MERID_MARKET_CATALOG_STALE_DOWN_S`.

## Disable switches
- Set `MERID_DISABLE_KALSHI_WS=1` or `MERID_DISABLE_MARKET_CATALOG=1` to intentionally disable; health shows `disabled` (not degraded).

## Recovery steps
1. WebSocket
   - Check reconnect churn via `reconnect_count`.
   - If `last_msg_ago_s` is stale, restart the WS bridge process or re-subscribe tickers.
2. Market catalog
   - Verify Kalshi REST availability; refresh manually if `age_s` is high.
   - If `market_count` is 0 but REST is up, confirm filters/timeframes are correct.

## Clear the banner
- Health returns to `healthy` once the WS feed is producing fresh messages and the catalog refreshes within thresholds. Removing disable flags also clears `disabled` state.
