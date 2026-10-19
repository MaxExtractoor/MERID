# Kalshi Live Trading Audit — Full Remediation Plan
**Date:** 2025  
**Auditor:** Cascade (Principal Engineer + Quant DevOps)  
**Status:** DRAFT — Pre-Live

---

## Executive Summary

The MERID Kalshi integration is **structurally sound** but has **5 concrete blockers** before live trading is safe. The 401 root cause is a combination of (1) key format mismatch (PKCS#1 vs PKCS#8), (2) demo credentials pointed at a live-ish elections endpoint, and (3) the `KALSHI_USE_DEMO=true` logic preventing the correct URL from being applied when `KALSHI_API_HOST` is set. A second critical issue is that `merid_core` rest_client uses a **different prod URL** (`api.kalshi.com`) than the correct elections URL in `merid/settings.py`.

---

## P0-P2 Remediation Table

| # | File | Issue | Severity | Fix | Test |
|---|------|-------|----------|-----|------|
| A1 | `.env` | `KALSHI_USE_DEMO=true` but `KALSHI_API_HOST=api.elections.kalshi.com` — demo flag causes `KalshiConfig.base_url` to return `demo-api.kalshi.co` while the signed path is built for elections. Key is a **demo** key. These are contradictory. | **P0** | Decide: test on demo (set host to `demo-api.kalshi.co`) OR go live (set `KALSHI_USE_DEMO=false` with live keys). See fix below. | `test_config_url_consistency` |
| A2 | `merid/event_venues/kalshi/models.py:209` | `if _api_host and not self.use_demo:` — **only** applies `KALSHI_API_HOST` override when `use_demo=False`. When demo=True, the custom host is silently ignored and `demo_rest_api_url` is used. | **P0** | Remove the `not self.use_demo` guard — always honour explicit `KALSHI_API_HOST` if set. | `test_kalshi_config_host_override_with_demo` |
| A3 | `merid_core/kalshi/rest_client.py:75` | `prod` env maps to `https://api.kalshi.com` — **wrong**. The correct live URL is `https://api.elections.kalshi.com`. `web/api/kalshi_api.py` passes `env="prod"` but the URL is wrong. | **P0** | Change to `https://api.elections.kalshi.com` | `test_rest_client_prod_url` |
| A4 | `kalshi_demo_private_key.pem` | Key uses legacy **PKCS#1** format (`-----BEGIN RSA PRIVATE KEY-----`). `cryptography` lib loads this fine, but Kalshi **requires the public key to be registered** on the dashboard. If public key is not uploaded yet, every RSA-signed request → 401. | **P0** | Upload `kalshi_public_key.pem` (matching public key) to Kalshi dashboard under API Keys. Validate with curl test below. | Manual dashboard check |
| A5 | `merid/event_venues/kalshi/client.py:377-378` | `_sign_headers` includes **body** in the signature message. Kalshi v2 docs specify: `timestamp + METHOD + path` only — **no body**. Body inclusion is the #1 cause of 401 on POST requests. | **P0** | Remove `+ body` from the `message` construction; set `body: str = ""` default is already there but callers pass it. | `test_sign_headers_no_body` |
| A6 | `merid/event_venues/kalshi/client.py:444` | Path prefix: `full_path = f"/trade-api/v2{path}"` — correct if `path` is `/portfolio/orders`. But `base_url` already contains the full URL `https://api.elections.kalshi.com/trade-api/v2`. The request URL is `base_url + path` = correct, but the **signed path** prepends `/trade-api/v2` separately. Double-check this doesn't result in `/trade-api/v2/trade-api/v2/...` by verifying `path` arg is always a relative path like `/portfolio/orders`. **Confirmed OK** — path is relative, URL is constructed as `base_url + path`. Signed path is `/trade-api/v2/portfolio/orders`. ✓ | Low | No change needed | Verified by inspection |
| A7 | `merid_core/kalshi/rest_client.py:145` | Signs `timestamp + METHOD + path` (correct) but strips query string with `split("?")[0]` — this is correct per Kalshi spec. ✓ | — | No change needed | — |
| B1 | `merid/event_venues/kalshi/client.py:69-72` | Module-level RSA key cache `_cached_private_key` shared globally. If two `KalshiVenueClient` instances use different keys (demo vs live), the second instantiation reuses the first key silently (cache never invalidated). | **P1** | Add key path to cache key: invalidate cache if `private_key_path` differs. | `test_rsa_cache_key_isolation` |
| B2 | `web/api/kalshi_api.py:92` | `_get_rest_client()` returns `None` if `key_path == "change_me"` — silently falls back to `merid_core` client. If `merid_core` is also broken (wrong URL), the endpoint returns empty data with no error logged at WARNING level. | **P1** | Raise/log at ERROR level if both clients fail; return 503 rather than empty 200. | `test_kalshi_balance_endpoint_no_client` |
| B3 | `merid/prediction/venue_gate.py` | `TradingMode.LIVE` gate requires `gate.live_enabled` but `MERID_PM_LIVE_ENABLED=false` in `.env` — live orders will always be blocked at `_route_live`. This is intentional for paper mode but must be flipped for live. | **P1** | Set `MERID_PM_LIVE_ENABLED=true` and `MERID_PM_TRADING_MODE=live` when ready to go live. | Go-live checklist gate |
| B4 | `merid/event_venues/kalshi/models.py:206-207` | `if not self.use_demo: self.use_demo = _use_demo` — this sets `use_demo` from env only if it's currently `False`. A hardcoded `KalshiConfig(use_demo=False)` would be overridden by env `KALSHI_USE_DEMO=true`. Subtle mode leak. | **P1** | Always override from env: `self.use_demo = _use_demo` unconditionally. | `test_use_demo_env_overrides_constructor` |
| C1 | `tests/event_venues/kalshi/test_kalshi_client_refactored.py` | No RSA signing unit tests — only password auth. `_sign_headers` has zero test coverage. A typo in the signing logic would pass all tests. | **P2** | Add `TestRSASigning` class (see test scaffold below). | New tests |
| C2 | `tests/` | No test mocks a **401 response** and verifies that the client surfaces it as an `OperationResult.fail` with `status_code=401`. Current tests only mock 200s and generic failures. | **P2** | Add `test_request_returns_401_operationresult`. | New tests |
| C3 | `merid/settings.py:161` | `KALSHI_PRIVATE_KEY_PATH: Optional[str] = Field(default="change_me", ...)` — default is the sentinel string `"change_me"`. Pydantic will happily pass this to `KalshiConfig.__post_init__` which checks `path != "change_me"` in one place but not `_get_rest_client`. | **P2** | Change default to `None`. | `test_settings_key_path_default_none` |

---

## P0 Fixes (Code Diffs)

### Fix A2: Always honour `KALSHI_API_HOST` regardless of demo flag

```python
# merid/event_venues/kalshi/models.py  line ~208-210
# BEFORE:
if _api_host and not self.use_demo:
    self.rest_api_url = _api_host

# AFTER:
if _api_host:
    if self.use_demo:
        self.demo_rest_api_url = _api_host
    else:
        self.rest_api_url = _api_host
```

### Fix A3: Correct prod URL in merid_core rest_client

```python
# merid_core/kalshi/rest_client.py  line ~73-77
# BEFORE:
elif env == "prod":
    self.base_url = "https://api.kalshi.com"

# AFTER:
elif env == "prod":
    self.base_url = "https://api.elections.kalshi.com"
```

### Fix A5: Remove body from RSA signature (CRITICAL)

```python
# merid/event_venues/kalshi/client.py  line ~377-378
# BEFORE:
ts_ms = str(int(time.time() * 1000))
message = ts_ms + method.upper() + path + body

# AFTER:
ts_ms = str(int(time.time() * 1000))
message = ts_ms + method.upper() + path
# Note: Kalshi v2 signs timestamp + METHOD + path only (no body)
```

Also update `_sign_headers` signature to drop the unused body param:

```python
# BEFORE:
def _sign_headers(self, method: str, path: str, body: str = "") -> Dict[str, str]:

# AFTER:
def _sign_headers(self, method: str, path: str) -> Dict[str, str]:
```

And in `_request_with_resilience`:

```python
# BEFORE:
body_str = json.dumps(json_data) if json_data else ""
full_path = f"/trade-api/v2{path}"
extra_headers = self._sign_headers(method.upper(), full_path, body_str)

# AFTER:
full_path = f"/trade-api/v2{path}"
extra_headers = self._sign_headers(method.upper(), full_path)
```

### Fix B1: RSA key cache isolation by path

```python
# merid/event_venues/kalshi/client.py  top of _authenticate_rsa
# BEFORE:
if _cached_private_key is not None:
    self._private_key = _cached_private_key
    ...

# AFTER:
_cache_path = self.config.private_key_path or ""
if _cached_private_key is not None and _cached_key_id == _cache_path:
    self._private_key = _cached_private_key
    ...
```

And when setting cache:

```python
_cached_private_key = self._private_key
_cached_key_id = self.config.private_key_path or (self.config.api_key[:8] if self.config.api_key else "unknown")
```

### Fix C3: Settings default for key path

```python
# merid/settings.py  line ~161
# BEFORE:
KALSHI_PRIVATE_KEY_PATH: Optional[str] = Field(default="change_me", ...)

# AFTER:
KALSHI_PRIVATE_KEY_PATH: Optional[str] = Field(default=None, ...)
```

---

## 401 Diagnostic Script (run this first)

```python
# python scripts/kalshi_auth_check.py
import time, base64, os
from pathlib import Path
from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.primitives.asymmetric import padding
import httpx

KEY_ID   = os.environ.get("KALSHI_API_KEY_ID", "06f1863e-ade1-4ca8-a406-7d8c9438de99")
KEY_PATH = os.environ.get("KALSHI_PRIVATE_KEY_PATH", "c:/Dev/MERID/kalshi_demo_private_key.pem")
BASE_URL = os.environ.get("KALSHI_API_HOST", "https://demo-api.kalshi.co/trade-api/v2")

with open(KEY_PATH, "rb") as f:
    key = serialization.load_pem_private_key(f.read(), password=None)

ts = str(int(time.time() * 1000))
path = "/trade-api/v2/portfolio/balance"
msg = (ts + "GET" + path).encode()
sig = key.sign(msg, padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.DIGEST_LENGTH), hashes.SHA256())
sig_b64 = base64.b64encode(sig).decode()

headers = {
    "KALSHI-ACCESS-KEY": KEY_ID,
    "KALSHI-ACCESS-TIMESTAMP": ts,
    "KALSHI-ACCESS-SIGNATURE": sig_b64,
    "Content-Type": "application/json",
}

resp = httpx.get(f"{BASE_URL}/portfolio/balance", headers=headers)
print(f"Status: {resp.status_code}")
print(f"Body: {resp.text[:500]}")
# Expected: 200 {"balance": {...}}
# If 401: key ID wrong, key not uploaded to dashboard, or wrong base URL
```

---

## Config Fix for Demo Testing

Update `.env`:

```ini
# For DEMO testing (kalshi_demo_private_key.pem + demo key ID)
KALSHI_API_HOST=https://demo-api.kalshi.co/trade-api/v2
KALSHI_API_KEY_ID=06f1863e-ade1-4ca8-a406-7d8c9438de99
KALSHI_PRIVATE_KEY_PATH=c:/Dev/MERID/kalshi_demo_private_key.pem
KALSHI_USE_DEMO=true
```

OR for LIVE:

```ini
# For LIVE trading (separate live keys required)
KALSHI_API_HOST=https://api.elections.kalshi.com/trade-api/v2
KALSHI_ENV=live
KALSHI_LIVE_API_KEY_ID=<your_live_key_id>
KALSHI_LIVE_PRIVATE_KEY_PATH=c:/Dev/MERID/kalshi_live_private_key.pem
KALSHI_USE_DEMO=false
MERID_PM_LIVE_ENABLED=true
MERID_PM_TRADING_MODE=live
MERID_LIVE_TRADING_UNLOCKED=true
```

---

## Tests to Add

### `tests/event_venues/kalshi/test_kalshi_rsa_signing.py`

```python
"""Unit tests for RSA signing correctness — P2 gap fill."""
import pytest, base64, time
from unittest.mock import patch, MagicMock
from cryptography.hazmat.primitives.asymmetric import rsa, padding
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.backends import default_backend
from merid.event_venues.kalshi.client import KalshiVenueClient
from merid.event_venues.kalshi.models import KalshiConfig


@pytest.fixture
def rsa_client():
    """Client with an in-memory RSA key (no disk I/O)."""
    import merid.event_venues.kalshi.client as mod
    mod._cached_private_key = None
    mod._cached_key_id = None
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048, backend=default_backend())
    config = KalshiConfig.__new__(KalshiConfig)
    config.api_key = "test-key-id"
    config.private_key_path = None
    config.private_key_pem = None
    config.use_demo = True
    config.email = None
    config.password = None
    config.timeout = 30.0
    config.ws_timeout = 60.0
    config.rest_api_url = "https://api.elections.kalshi.com/trade-api/v2"
    config.demo_rest_api_url = "https://demo-api.kalshi.co/trade-api/v2"
    config.demo_ws_api_url = "wss://demo-api.kalshi.co/trade-api/ws/v2"
    config.ws_api_url = "wss://api.elections.kalshi.com/trade-api/ws/v2"
    client = KalshiVenueClient(config)
    client._private_key = private_key
    client._auth_mode = "rsa"
    return client, private_key


def test_sign_headers_returns_required_keys(rsa_client):
    client, _ = rsa_client
    hdrs = client._sign_headers("GET", "/trade-api/v2/portfolio/balance")
    assert "KALSHI-ACCESS-KEY" in hdrs
    assert "KALSHI-ACCESS-TIMESTAMP" in hdrs
    assert "KALSHI-ACCESS-SIGNATURE" in hdrs


def test_sign_headers_timestamp_is_milliseconds(rsa_client):
    client, _ = rsa_client
    now_ms = int(time.time() * 1000)
    hdrs = client._sign_headers("GET", "/trade-api/v2/portfolio/balance")
    ts = int(hdrs["KALSHI-ACCESS-TIMESTAMP"])
    # Within 5 seconds
    assert abs(ts - now_ms) < 5000


def test_sign_headers_no_body_in_message(rsa_client):
    """Signature must be over timestamp+METHOD+path ONLY — no body."""
    client, private_key = rsa_client
    ts_before = str(int(time.time() * 1000))
    hdrs = client._sign_headers("POST", "/trade-api/v2/portfolio/orders")
    sig = base64.b64decode(hdrs["KALSHI-ACCESS-SIGNATURE"])
    ts = hdrs["KALSHI-ACCESS-TIMESTAMP"]
    # Verify correct message (no body)
    msg_correct = (ts + "POST" + "/trade-api/v2/portfolio/orders").encode()
    pub = private_key.public_key()
    pub.verify(sig, msg_correct, padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.DIGEST_LENGTH), hashes.SHA256())
    # Should not raise — if body was included this verify would fail


def test_sign_headers_different_on_each_call(rsa_client):
    """Each call should produce a fresh timestamp → different signature."""
    client, _ = rsa_client
    h1 = client._sign_headers("GET", "/trade-api/v2/portfolio/balance")
    time.sleep(0.002)
    h2 = client._sign_headers("GET", "/trade-api/v2/portfolio/balance")
    # Timestamps may differ; signatures always differ due to PSS randomness
    assert h1["KALSHI-ACCESS-SIGNATURE"] != h2["KALSHI-ACCESS-SIGNATURE"]


@pytest.mark.asyncio
async def test_request_401_returns_operationresult_fail():
    """A 401 response must surface as OperationResult.fail with status_code=401."""
    import respx
    from httpx import Response
    config = KalshiConfig(email="t@t.com", password="pw", use_demo=True)
    client = KalshiVenueClient(config)
    with respx.mock:
        respx.post("https://demo-api.kalshi.co/trade-api/v2/login").mock(
            return_value=Response(200, json={"token": "tok", "member_id": "m"})
        )
        respx.get("https://demo-api.kalshi.co/trade-api/v2/portfolio/balance").mock(
            return_value=Response(401, json={"error": "unauthorized"})
        )
        await client.connect()
        result = await client._request_with_resilience("GET", "/portfolio/balance")
        assert not result.success
        assert result.status_code == 401
```

---

## End-to-End Execution Path — Verified

```
OrderIntent(ticker, side, action, price_cents, count)
  → route_order_async(intent)
    → _resolve_mode()              [reads get_trade_mode() → trading.trade_mode.TradeMode]
    → _check_intent_risk()         [price/size/side validation]
    → _check_sanity()              [OrderSanityChecker — portfolio notional cap]
    [LIVE path only]:
    → risk_controller.can_trade()  [kill switch — fail-closed ✓]
    → gate.live_enabled            [venue_gate.live_enabled — currently False ✓]
    → KalshiRiskManager.check_order()  [position limits, category caps]
    → CategoryExposureTracker      [correlated-market stacking]
    → SentimentBus scaling         [size reducer on adverse regime]
    → client.connect()
      → _ensure_client()
        → _authenticate()
          → _authenticate_rsa()    [loads key, sets _auth_mode="rsa"]
    → client.get_market(ticker)    [A5: live market condition re-validate]
    → client.place_order_result(VenueOrder)
      → _request_with_resilience("POST", "/portfolio/orders", json_data=...)
        → _rate_limiter.acquire()  [token bucket — basic tier 10w/s]
        → _sign_headers(method, /trade-api/v2/portfolio/orders)  [RSA per-request]
        → httpx.request(url, headers, json)
        → parse OperationResult
    → OrderResult(status, fill, latency_ms)
```

**Gaps identified:**
- No fill confirmation loop — partial fills (`accepted_live` status) have no retry/polling
- `cancel_order` uses `POST /portfolio/orders/{id}/cancel` — verify this matches current Kalshi v2 spec (was `DELETE` in older versions)
- Position sync not triggered after a fill — risk manager exposure tracking relies on `record_order()` which is called but doesn't fetch live positions

---

## Top 3 Failure Modes + Mitigations

| # | Failure | Mitigation |
|---|---------|------------|
| 1 | **RSA key not uploaded to Kalshi dashboard** → every request 401 forever | Manually upload public key at `dashboard.kalshi.com → API Keys`. Run diagnostic script above to verify. |
| 2 | **Demo key used against elections/live endpoint** → 401 or wrong account balance | Fix A1/A2: Match key pair to environment. Never cross demo key with live URL. |
| 3 | **Body included in signature on POST orders** → 401 only on writes (GETs pass) | Fix A5: Remove body from `_sign_headers`. This is the most likely cause if GET /portfolio/balance works but POST /portfolio/orders fails. |

---

## GO-LIVE CHECKLIST (Runnable)

```bash
# ── Step 1: Validate auth fixes ───────────────────────────────────────────
python scripts/kalshi_auth_check.py
# Expected: Status: 200

# ── Step 2: Run auth unit tests ───────────────────────────────────────────
pytest tests/event_venues/kalshi/test_kalshi_rsa_signing.py -v
# Expected: 5/5 pass

# ── Step 3: Run full Kalshi test suite ────────────────────────────────────
pytest tests/event_venues/kalshi/ tests/test_kalshi_deep_integration.py -v --tb=short
# Expected: all pass

# ── Step 4: Verify demo paper session (30 min) ────────────────────────────
# Set .env: KALSHI_USE_DEMO=true, MERID_PM_TRADING_MODE=paper
# Start server: uvicorn web.main:app --reload
# Confirm in logs: "Kalshi RSA auth ready"
# Confirm no 401 lines in logs after 5 min
curl -s http://localhost:8011/api/v1/kalshi/health | python -m json.tool

# ── Step 5: Paper order smoke test ───────────────────────────────────────
curl -s -X POST http://localhost:8011/api/v1/kalshi/orders \
  -H "Content-Type: application/json" \
  -d '{"ticker":"KXBTCD-25DEC-T90000","side":"yes","action":"buy","price_cents":45,"count":1,"mode":"paper"}'
# Expected: {"status": "filled_paper", ...}

# ── Step 6: Live demo endpoint test (read-only) ───────────────────────────
# Set .env: KALSHI_USE_DEMO=true with CORRECT demo base URL
curl -s http://localhost:8011/api/v1/kalshi/balance
# Expected: {"balance": ..., "locked_balance": ...}  NOT {"balance": null}

# ── Step 7: Live unlock sequence ─────────────────────────────────────────
# [ ] MERID_LIVE_TRADING_UNLOCKED=true
# [ ] MERID_PM_LIVE_ENABLED=true
# [ ] MERID_PM_TRADING_MODE=live
# [ ] KALSHI_USE_DEMO=false
# [ ] KALSHI_ENV=live
# [ ] KALSHI_LIVE_API_KEY_ID=<live key id>
# [ ] KALSHI_LIVE_PRIVATE_KEY_PATH=<live key path>
# [ ] Live key uploaded to Kalshi dashboard ← MANUAL STEP

# ── Step 8: Live canary (1 micro-order) ──────────────────────────────────
# Place 1 contract at market's best bid via UI or API
# Confirm order_id returned, filled_live status
# Confirm position visible in /api/v1/kalshi/positions
# Confirm PnL non-zero in /api/v1/kalshi/pnl

# ── Step 9: Risk params ──────────────────────────────────────────────────
# [ ] MERID_PM_MAX_NOTIONAL_PER_MARKET=500.0 (review for canary: set to 50.0)
# [ ] MERID_PM_MAX_DAILY_LOSS=250.0
# [ ] Kill switch armed: curl -X POST /api/v1/kalshi/kill-switch -d '{"action":"arm"}'

# ── Step 10: 24h health check ────────────────────────────────────────────
# [ ] Zero 401s in logs
# [ ] WebSocket stable (no reconnects > 5/hour)
# [ ] Reconciliation: curl /api/v1/reconciliation/status → 0 discrepancies
```

---

## Post-Live Monitoring Playbook

1. **Auth failure spike** (>3 401s/min): Check clock skew (`ntpdate -q pool.ntp.org`), re-upload public key if rotated
2. **Circuit breaker open** (logged as `[kalshi] circuit open`): Automatic recovery after 30s; manual reset via `/api/v1/kalshi/health`
3. **Rate limit 429s**: Downgrade `rate_tier` from `basic` (10 write/s) or batch orders; contact Kalshi for tier upgrade
4. **Partial fills not resolved**: Poll `/api/v1/kalshi/orders` every 5s for `accepted_live` status; cancel and resubmit if stale >60s
5. **WS disconnect**: `ws_bridge` has reconnect logic; if disconnected >5min, force restart via supervisor
