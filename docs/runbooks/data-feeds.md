# Data Feeds Runbook

## Overview
MERID consumes: Kalshi WebSocket (orderbook + fills), live price feeds (CoinGecko/Binance), and optionally news/social feeds. Feed health is surfaced via `ws_feed_disconnected`, `ws_kalshi_seq_gap`, `feed_staleness`, and `instrument_staleness` alerts.

---

## Start / Stop / Restart

Feeds are started automatically at server boot inside `_app_lifespan`.

```powershell
# Check feed status
curl http://localhost:8011/api/v1/kalshi/ws/status
curl http://localhost:8011/api/v1/system/observability | python -m json.tool

# Force reconnect Kalshi WS bridge (no restart needed)
curl -X POST http://localhost:8011/api/v1/kalshi/ws/reconnect

# Full restart
sudo systemctl restart merid-api
```

---

## Health Check

```powershell
# Kalshi WS connected?
curl http://localhost:8011/api/v1/system/alerts | python -m json.tool | grep ws_

# Price feed alive?
curl http://localhost:8011/api/v1/real-data/prices

# Instrument data fresh?
curl http://localhost:8011/api/v1/system/alerts | python -m json.tool | grep instrument_staleness
```

---

## Common Failure Modes

### Kalshi WS disconnected
- **Alert:** `ws_feed_disconnected` or `ws_kalshi_seq_gap`
- **Cause:** Network blip, Kalshi token expiry, or rate-limit disconnect.
- **Fix sequence:**
  1. Check `GET /api/v1/kalshi/ws/status` for `reconnect_count` and `consecutive_auth_failures`.
  2. If `consecutive_auth_failures >= 3`: credential rotation needed — check `KALSHI_API_KEY_ID` / `KALSHI_PRIVATE_KEY_PEM` in env.
  3. Otherwise: the bridge auto-reconnects with exponential backoff. Wait 60s, then check again.
  4. If still disconnected after 5 min: restart server.

### Sequence gaps (`ws_kalshi_seq_gap`)
- **Cause:** Packet loss or fast reconnect during high-volume trading.
- **Effect:** Orderbook cache for affected markets is invalidated; prices may be stale.
- **Fix:** Monitor `seq_gaps_total` — if it keeps growing, force reconnect. If it stops growing, the WS recovered cleanly.

### Live price feed stale (`feed_staleness`)
- **Cause:** CoinGecko/Binance API rate-limit or network issue.
- **Fix:** Check `real_data_fallback_counts.live_price_feed` in observability output. If > 0, the feed is erroring. Check API key quotas (`COINGECKO_API_KEY`). The system falls back to last-known prices; execution is not halted.

### Instruments not refreshed (`instrument_staleness`)
- **Cause:** Kalshi REST API call for market list failing.
- **Fix:** Check `GET /api/v1/kalshi/markets` for errors. Verify `KALSHI_USE_DEMO` matches your environment. If demo credentials used in prod, change to prod credentials and restart.

---

## Escalation Path
1. `ws_kalshi_seq_gap` critical + growing → page on-call immediately (stale prices = bad fills).
2. `instrument_staleness` > 10 min → page on-call (no new markets discoverable).
3. Price feed stale > 30 min in LIVE mode → halt trading via kill switch, then investigate.
