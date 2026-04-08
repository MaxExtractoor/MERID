# Kalshi Integration Bug-Hunt Report

**Date:** 2026-04-08  
**Scope:** `merid/event_venues/kalshi/` + all callers (settings, models, ws, ws_bridge, market_catalog, execution gate)  
**Goal:** End-to-end audit before live crypto/FX trading restart on Kalshi

---

## Files Touched

| File | Change | Reason |
|---|---|---|
| `merid/event_venues/kalshi/invariants.py` | **Created** | New module: canonical URL constants + validation functions |
| `merid/event_venues/kalshi/models.py` | **Fixed** | `KalshiConfig` default REST/WS URLs confirmed as `api.elections.kalshi.com` (correct production host) |
| `merid/settings.py` | **Fixed** | `KALSHI_API_HOST` default confirmed as `https://api.elections.kalshi.com/trade-api/v2` |
| `merid/event_venues/kalshi/ws.py` | **Improved** | Added verbose URL + environment logging in `connect()` and on connect failure |
| `merid/event_venues/kalshi/ws_bridge.py` | **Improved** | Added URL logging on connect failure + first-message latency logging |
| `tests/event_venues/kalshi/test_invariants.py` | **Created** | 40 unit tests covering accept/reject/env-match/startup-gate scenarios |
| `scripts/kalshi_dryrun.py` | **Created** | Pre-restart dry-run verification script |

---

## Root Cause Found

**Primary bug:** A prior change incorrectly changed `KalshiConfig` and `settings.KALSHI_API_HOST`
away from `https://api.elections.kalshi.com/trade-api/v2` to `https://api.kalshi.com/trade-api/v2`.
The bare `api.kalshi.com` hostname is **not** a documented Kalshi endpoint and does not resolve,
causing every REST call to fail at the DNS/connection level. The correct production endpoint is
`api.elections.kalshi.com`.

> **Important note on hostname:** `api.elections.kalshi.com` is Kalshi's official
> production trade API for **all** markets (crypto, FX, elections, etc.).
> Despite the "elections" in the hostname, it is NOT elections-only.
> This is the endpoint documented by Kalshi for live real-money trading.

This caused the market catalog to fail REST calls, returning zero markets, which
triggered `Dependencies degraded: market_catalog` and forced the execution gate into
`LIMITED (reduce-only)` mode — and also tripped the `kalshi_live` circuit breaker.

---

## Correct Kalshi Endpoints

| Environment | REST base URL | WebSocket URL |
|---|---|---|
| **Live (production)** | `https://api.elections.kalshi.com/trade-api/v2` | `wss://api.elections.kalshi.com/trade-api/ws/v2` |
| **Demo/sandbox** | `https://demo-api.kalshi.co/trade-api/v2` | `wss://demo-ws.kalshi.co/v2` |

---

## Changes and Reasons

### 1. `merid/event_venues/kalshi/invariants.py` (new)

**Constants:**
- `LIVE_REST_BASE = "https://api.elections.kalshi.com/trade-api/v2"` — correct live endpoint
- `LIVE_WS_BASE = "wss://api.elections.kalshi.com/trade-api/ws/v2"` — correct live WS endpoint
- `VALID_KALSHI_API_PATTERNS` — accepts `api.elections.kalshi.com` (live) and `demo-api.kalshi.co` (demo)

**Functions:** `assert_valid_rest_url`, `assert_valid_ws_url`, `validate_config_env_match`, `validate_config_or_raise`.

Accepts `api.elections.kalshi.com` and `demo-api.kalshi.co`. Rejects `api.kalshi.com` (bare, undocumented) and other unknown hosts.

### 2. `merid/event_venues/kalshi/models.py`

Restored `KalshiConfig` defaults to the documented production endpoints:

```python
rest_api_url: str = "https://api.elections.kalshi.com/trade-api/v2"
ws_api_url:   str = "wss://api.elections.kalshi.com/trade-api/ws/v2"
```

### 3. `merid/settings.py`

Restored `KALSHI_API_HOST` default to `https://api.elections.kalshi.com/trade-api/v2`.

### 4. `merid/event_venues/kalshi/ws.py` and `ws_bridge.py`

Improved connect logging: URL, environment, auth method, first-message latency.

---

## Tests Added

**File:** `tests/event_venues/kalshi/test_invariants.py` — **40 tests**, all passing.

Key assertions:
- `api.elections.kalshi.com` is accepted as the live host
- `api.kalshi.com` (bare) is rejected with a message naming `api.elections.kalshi.com`
- Demo URLs are accepted for demo env, rejected for live env
- `KalshiConfig` field defaults pass invariant checks

```bash
python -m pytest tests/event_venues/kalshi/test_invariants.py -v
```

---

## Dry-Run Script

```bash
KALSHI_ENV=live python scripts/kalshi_dryrun.py
```

Expected output (with correct config):
```
✔ REST URL is valid: https://api.elections.kalshi.com/trade-api/v2
✔ WS URL is valid: wss://api.elections.kalshi.com/trade-api/ws/v2
✔ KALSHI_ENV and config URLs are consistent
```

---

## Pre-Restart Checklist

- [ ] `KALSHI_ENV=live` is set
- [ ] `KALSHI_API_HOST` = `https://api.elections.kalshi.com/trade-api/v2` (or left at default)
- [ ] `KALSHI_API_KEY_ID` set to valid API key ID
- [ ] `KALSHI_PRIVATE_KEY_PATH` or `KALSHI_PRIVATE_KEY_PEM` configured with RSA private key
- [ ] `KALSHI_USE_DEMO=false`
- [ ] Restart the process to reset the `kalshi_live` circuit breaker
- [ ] `python scripts/kalshi_dryrun.py` exits 0 (no blocking issues)
- [ ] After startup: `/api/health` shows `market_catalog` healthy, WS healthy, gate = `FULL`

---

## Is It Production-Ready?

**Yes, conditionally.** The endpoints have been corrected to use Kalshi's documented production API
(`api.elections.kalshi.com`), which serves all markets including crypto and FX despite the hostname.
The `invariants.py` module validates configurations at startup. The 40 unit tests and dry-run script
provide a repeatable pre-restart verification workflow. After restarting the process (which resets the
open circuit breaker), and given correct credentials and `KALSHI_ENV=live`, the integration is ready
for the next live startup.
