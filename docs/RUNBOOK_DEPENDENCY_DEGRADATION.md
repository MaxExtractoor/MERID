LIMITED / LIVE – Dependencies degraded: kalshi_websocket, market_catalog
=======================================================================

Health surface
--------------
- GET `/api/v1/dependencies/health` → `overall_status` + per-dependency blocks.
- `/api/system/health` and `/api/v1/system/health` embed the same `dependencies` block.
- Status values: `healthy`, `degraded`, `down`, `disabled`. Disabled means explicitly turned off (env flags).

Kalshi WebSocket (`kalshi_websocket`)
-------------------------------------
- Health fields: `running`, `connected`, `last_message_age_s`, `subscriptions`, `reconnects`, `events_forwarded`.
- Typical failure modes:
  - `bridge_not_running` → WS bridge task never started.
  - `ws_not_connected` → auth/URL/env issue.
  - `stale_stream` → no messages for > WS_MAX_STALE_S (default 45s).
- If you see:
  - `bridge_not_running`: restart WS bridge/stack; verify `get_ws_bridge().summary()` shows `running: true`.
  - `ws_not_connected`: check Kalshi creds/env (prod vs demo), clock skew, network; restart bridge.
  - `stale_stream`: inspect Kalshi WS status/upstream incidents; confirm subscriptions count > 0; consider reconnect.
  - Intentional stop: set `MERID_DISABLE_KALSHI_WS=true` (marks `disabled`, no banner).

Market catalog (`market_catalog`)
---------------------------------
- Health fields: `market_count`, `last_refresh`, `age_seconds`, `categories`, `assets`, `timeframes`, `refreshing`.
- Typical failure modes:
  - `empty_catalog` → refresh returned zero markets or filters too strict.
  - `stale_catalog`/`no_refresh_timestamp` → refresh loop stuck or clock issues.
- If you see:
  - `empty_catalog`: run `/api/v1/kalshi/catalog/refresh`; check Kalshi REST; validate filters for BTC/ETH/SOL/XRP/DOGE.
  - `stale_catalog`: confirm refresh task running; inspect logs for REST errors; restart catalog task if stuck.
  - Intentional stop: set `MERID_DISABLE_MARKET_CATALOG=true` (marks `disabled`, no banner).

60-second sanity checklist
--------------------------
- Call `/api/v1/dependencies/health`.
- For WS: `status` healthy, `last_message_age_s` < 45s, `subscriptions` > 0.
- For catalog: `status` healthy, `market_count` > 0, `age_seconds` < 300s.
- If any `degraded`/`down`: read `issues`, check logs, restart the affected component; only mark `disabled` if intentionally offline.
