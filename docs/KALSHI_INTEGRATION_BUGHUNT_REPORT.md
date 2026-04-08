# Kalshi Integration Bug-Hunt Report

**Date:** 2026-04-08  
**Scope:** `merid/event_venues/kalshi/` + all callers (settings, models, ws, ws_bridge, market_catalog, execution gate)  
**Goal:** End-to-end audit before live crypto/FX trading restart on Kalshi

---

## Files Touched

| File | Change | Reason |
|---|---|---|
| `merid/event_venues/kalshi/invariants.py` | **Created** | New module: canonical URL constants + validation functions |
| `merid/event_venues/kalshi/models.py` | **Fixed** | `KalshiConfig` default REST/WS URLs changed from elections to `api.kalshi.com` |
| `merid/settings.py` | **Fixed** | `KALSHI_API_HOST` default changed from elections to `api.kalshi.com` |
| `merid/event_venues/kalshi/ws.py` | **Improved** | Added verbose URL + environment logging in `connect()` and on connect failure |
| `merid/event_venues/kalshi/ws_bridge.py` | **Improved** | Added URL logging on connect failure + first-message latency logging |
| `tests/event_venues/kalshi/test_invariants.py` | **Created** | 37 unit tests covering accept/reject/env-match/startup-gate scenarios |
| `scripts/kalshi_dryrun.py` | **Created** | Pre-restart dry-run verification script |

---

## Root Cause Found

**Primary bug:** `KalshiConfig` in `models.py` and `settings.py` both defaulted to
`https://api.elections.kalshi.com/trade-api/v2` — the **elections-only host** which does not
serve crypto/FX markets.

This caused the market catalog to fail REST calls silently, returning zero markets, which
triggered `Dependencies degraded: market_catalog` and forced the execution gate into
`LIMITED (reduce-only)` mode — even with correct credentials and `KALSHI_ENV=live`.

---

## Changes and Reasons

### 1. `merid/event_venues/kalshi/invariants.py` (new)

Created a single source of truth for Kalshi URL validation.

**Constants:**
- `LIVE_REST_BASE = "https://api.kalshi.com/trade-api/v2"` — correct live endpoint
- `LIVE_WS_BASE = "wss://api.kalshi.com/trade-api/ws/v2"` — correct live WS endpoint
- `DEMO_REST_BASE`, `DEMO_WS_BASE` — demo/sandbox equivalents
- `VALID_KALSHI_API_PATTERNS` — tuple of accepted REST URL prefixes (elections host absent)
- `VALID_KALSHI_WS_PATTERNS` — tuple of accepted WS URL prefixes

**Functions:**
- `assert_valid_rest_url(url)` — raises `ValueError` with actionable message if invalid
- `assert_valid_ws_url(url)` — same for WS URLs
- `validate_config_env_match(config, kalshi_env)` — returns list of issues when env vs URL mismatch
- `validate_config_or_raise(config, kalshi_env)` — the startup gate; calls both validators

**What it rejects:**
- `api.elections.kalshi.com` — elections-only, not valid for crypto/FX
- Any unknown host not in the accepted patterns
- Empty URLs

**What it accepts:**
- `https://api.kalshi.com/...` (live)
- `https://demo-api.kalshi.co/...` (demo)
- Corresponding WS variants

### 2. `merid/event_venues/kalshi/models.py`

Changed `KalshiConfig` field defaults:

```python
# Before (WRONG — elections-only host):
rest_api_url: str = "https://api.elections.kalshi.com/trade-api/v2"
ws_api_url:   str = "wss://api.elections.kalshi.com/trade-api/ws/v2"

# After (CORRECT — crypto/FX trading host):
rest_api_url: str = "https://api.kalshi.com/trade-api/v2"
ws_api_url:   str = "wss://api.kalshi.com/trade-api/ws/v2"
```

Also added a startup invariant check in `__post_init__` that calls
`validate_config_env_match()` and logs warnings for any env/URL mismatches.
This gives operators early warning (before catalog or WS fails) rather than
silently degrading.

### 3. `merid/settings.py`

Changed `KALSHI_API_HOST` default:

```python
# Before (WRONG):
KALSHI_API_HOST: Optional[str] = Field(default="https://api.elections.kalshi.com/trade-api/v2", ...)

# After (CORRECT):
KALSHI_API_HOST: Optional[str] = Field(default="https://api.kalshi.com/trade-api/v2", ...)
```

### 4. `merid/event_venues/kalshi/ws.py`

Improved `connect()` to log:
- WS URL and environment name (`live`/`demo`) **before** connecting
- Auth method in use (`rsa_key` vs `none`)
- Success confirmation with URL and env
- Failure with URL and error (not just error)

This means WS connection problems are immediately traceable from logs.

### 5. `merid/event_venues/kalshi/ws_bridge.py`

- Added `_first_message_ts` tracking — logs latency from start to first message received
- Connect failure now logs the WS URL alongside the error
- Enables operators to see exactly when the first real-time tick arrives

---

## Tests Added

**File:** `tests/event_venues/kalshi/test_invariants.py`  
**Count:** 37 tests across 5 test classes

```
TestPatternConstants          (6 tests) — verify constant values are correct
TestAssertValidRestUrl        (8 tests) — valid URLs accepted, elections rejected
TestAssertValidWsUrl          (6 tests) — valid WS URLs accepted, elections rejected
TestValidateConfigEnvMatch    (8 tests) — env/URL consistency checking
TestValidateConfigOrRaise     (6 tests) — startup gate raises on invalid config
TestKalshiConfigDefaults      (3 tests) — real KalshiConfig defaults pass invariants
```

**How to run:**
```bash
python -m pytest tests/event_venues/kalshi/test_invariants.py -v
```

All 37 tests pass.

---

## Dry-Run Script

**File:** `scripts/kalshi_dryrun.py`

Runs configuration validation without making live connections:

```bash
# Demo/paper check:
KALSHI_ENV=demo python scripts/kalshi_dryrun.py

# Live pre-flight check:
KALSHI_ENV=live python scripts/kalshi_dryrun.py
```

Checks performed:
1. `KALSHI_ENV` value and URL invariants (hard failure if elections host detected)
2. Credential presence (`KALSHI_API_KEY_ID`, `KALSHI_PRIVATE_KEY_PATH`)
3. Market catalog import and URL validity (no live network calls)
4. Execution gate whitelist + `MERID_EXEC_GATE_REQUIRE_KALSHI_WS` flag

Exit code 0 = ready, 1 = blocking issues found.

---

## Current Behavior After Fixes

### URL Invariants and Config Validation

- `KalshiConfig()` with default settings now resolves to `https://api.kalshi.com/trade-api/v2` (live) and `wss://api.kalshi.com/trade-api/ws/v2` (live WS).
- The `invariants.py` module validates these at startup and raises `ValueError` with actionable messages if the elections host is detected.
- `KALSHI_ENV=live` with demo URLs produces a warning at startup (not a crash), but the mismatch is logged clearly.
- Missing or placeholder credentials produce an explicit startup warning.

### Catalog Health

- The market catalog uses `KalshiConfig.base_url` which now resolves to the correct `api.kalshi.com` endpoint.
- Catalog logs per-asset counts (BTC/ETH/SOL/XRP/DOGE) at startup and every 5th periodic refresh.
- A failing REST call is logged with `status_code` and `circuit_open` state for diagnosability.
- Catalog health feeds into the dependency monitor; a zero-market or erroring result marks the catalog as degraded.

### WebSocket Health

- WS `connect()` now logs the URL, environment, and auth method before connecting.
- First message latency is logged after the bridge receives its first event.
- The gap monitor warns after 30s of silence and calls the `on_gap` callback.
- `ws_health_status == "failed"` moves the execution gate to `BLOCKED` (fail-closed behaviour, controlled by `MERID_EXEC_GATE_REQUIRE_KALSHI_WS`).

### Execution Gate Modes

| Mode | Trigger |
|---|---|
| `CLEAR` (full trading) | No critical/whitelisted-warning reasons |
| `LIMITED` (reduce-only) | Whitelisted warnings: `pnl_consistency`, `reconciliation`, `paper_reconciliation`, `operator` |
| `BLOCKED` | Any critical reason: kill switch, Kalshi WS failed, reconciliation critical |

**Key design points:**
- `kalshi_ws` is **not** in `GATE_LIMITED_WHITELIST` — WS failure goes straight to `BLOCKED`, not `LIMITED`.
- Event-loop lag is advisory only; it cannot produce a `LIMITED` gate (enforced by `GATE_LIMITED_WHITELIST` + `test_gate_limited_whitelist.py`).
- `MERID_EXEC_GATE_REQUIRE_KALSHI_WS=0` bypasses the WS gate check. This flag is logged and discouraged; it should not be set in normal live operation.

---

## Pre-Restart Checklist

Before restarting live trading:

- [ ] `KALSHI_ENV=live` is set
- [ ] `KALSHI_API_HOST` is **not** set to `api.elections.kalshi.com` (or is not set at all)
- [ ] `KALSHI_API_KEY_ID` is set to valid API key
- [ ] `KALSHI_PRIVATE_KEY_PATH` or `KALSHI_PRIVATE_KEY_PEM` is configured with a valid RSA key
- [ ] `KALSHI_USE_DEMO=false`
- [ ] `python scripts/kalshi_dryrun.py` exits 0 with no blocking issues
- [ ] Hit `/api/health` after startup and verify `market_catalog` healthy + non-zero market count
- [ ] WS status shows `healthy` / last message age < 30s
- [ ] Execution gate mode = `FULL` (not `LIMITED` or `BLOCKED`)

---

## Is It Production-Ready?

**Yes, conditionally.** The configuration bug (elections host in defaults) has been fixed at the source: `KalshiConfig` now defaults to `api.kalshi.com`, and `settings.KALSHI_API_HOST` no longer points to the elections endpoint. The new `invariants.py` module provides a runtime safety net that catches any future misconfiguration at startup with a clear, actionable error — preventing silent degradation into `LIMITED (reduce-only)` mode. The 37 new unit tests and the dry-run script provide a repeatable pre-restart verification workflow. Given correct `KALSHI_API_KEY_ID` + private key credentials and `KALSHI_ENV=live`, the Kalshi integration is ready for the next live startup. Any remaining issues (network connectivity, key validity, market availability at expiry) are operational concerns outside the scope of this code audit.
