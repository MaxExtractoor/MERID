# 15m App Identity and Health Validation

**Purpose**: Validate that only `web.main_15m:app` serves the 15m trading system and health.

---

## Single Source of Truth

**Production 15m**: Only `web.main_15m:app` with `MERID_PROFILE=kalshi_crypto_15m_v2`

**Uvicorn Command**:
```bash
MERID_PROFILE=kalshi_crypto_15m_v2 uvicorn web.main_15m:app --host 0.0.0.0 --port 8011 --log-level info
```

---

## Profile Guards

### web.main_15m.py
**Location**: Lines 63-70 (lifespan validation)
```python
profile = os.getenv("MERID_PROFILE", "").lower()
if profile != "kalshi_crypto_15m_v2":
    logger.error(
        "Invalid profile for web.main_15m: %s (expected kalshi_crypto_15m_v2)",
        profile,
    )
    raise ValueError(
        f"web.main_15m is only for kalshi_crypto_15m_v2 profile, got {profile}"
    )
```

**Location**: Lines 880-885 (main guard)
```python
if __name__ == "__main__":
    profile = os.getenv("MERID_PROFILE", "").lower()
    if profile != "kalshi_crypto_15m_v2":
        print("ERROR: web.main_15m only supports kalshi_crypto_15m_v2 profile")
        print(f"Current profile: {profile}")
        print("Set MERID_PROFILE=kalshi_crypto_15m_v2")
        exit(1)
```

### web.main_legacy.py
**Location**: Lines 671-679 (create_app guard)
```python
def create_app(lifespan=None) -> FastAPI:
    # PROFILE GUARD: Explicitly forbid kalshi_crypto_15m_v2 in legacy main
    # The 15m crypto profile MUST use web.main_15m:app only
    profile = os.getenv("MERID_PROFILE", "").lower()
    if profile == "kalshi_crypto_15m_v2":
        raise ValueError(
            "web.main_legacy (legacy main) does not support kalshi_crypto_15m_v2 profile. "
            "Use web.main_15m:app instead with MERID_PROFILE=kalshi_crypto_15m_v2. "
            "The 15m crypto profile requires the lean 15m-specific entrypoint."
        )
```

---

## Health Endpoint

### web.main_15m.py
**Route**: `/api/health` (only)
**Location**: Lines 803-841

**Response Schema**:
```json
{
  "status": "healthy",
  "app": "merid_15m_kalshi_crypto",
  "profile": "kalshi_crypto_15m_v2",
  "port": 8011,
  "demo_mode": false,
  "loop": {
    "tick": 123,
    "cycle_count": 120,
    "error_count": 0,
    "uptime_seconds": 600.5,
    "last_cycle_at": "2026-05-18T12:45:00.123456Z"
  },
  "services": {
    "kalshi_client": {"status": "running", "started_at": 1716048000.0},
    "bankroll": {"status": "running", "started_at": 1716048005.0},
    "catalog": {"status": "running", "started_at": 1716048010.0, "allowed_series": ["KXBTC15M", "KXETH15M", "KXSOL15M", "KXXRP15M", "KXDOGE15M"]},
    "market_state": {"status": "running", "started_at": 1716048015.0},
    "ws_bridge": {"status": "running", "started_at": 1716048020.0},
    "fills_poller": {"status": "running", "started_at": 1716048025.0},
    "settlement_poller": {"status": "running", "started_at": 1716048030.0},
    "live_price_feed": {"status": "running", "started_at": 1716048035.0},
    "agent_grid": {"status": "loaded", "agent_count": 5, "agents": ["BTC_15M", "ETH_15M", "SOL_15M", "XRP_15M", "DOGE_15M"]},
    "loop": {"status": "running", "started_at": 1716048040.0}
  },
  "timestamp": "2026-05-18T12:45:30.123456Z"
}
```

**Error Handling**:
- `loop.summary()` wrapped in try/except (won't 500 on summary failure)
- `_startup_state["services"]` accessed via `.get()` with default (won't 500 on missing key)
- All exceptions caught and logged, returns 200 with degraded data

### web.main_legacy.py
**Health Routes**: `/healthz`, `/api/v1/health/startup` (different endpoints, no conflict)

---

## Validation Script

### PowerShell
```powershell
# Validate 15m app is serving on port 8011
$r = Invoke-WebRequest -Uri http://127.0.0.1:8011/api/health -UseBasicParsing
$r.StatusCode
$r.Content

# Expected: StatusCode = 200, Content is JSON with app="merid_15m_kalshi_crypto" and profile="kalshi_crypto_15m_v2"
```

### Bash
```bash
# Validate 15m app is serving on port 8011
curl -s http://127.0.0.1:8011/api/health | jq .

# Expected: JSON with app="merid_15m_kalshi_crypto" and profile="kalshi_crypto_15m_v2"
```

---

## Validation Checklist

- [x] web.main_15m raises if profile != kalshi_crypto_15m_v2 (lifespan)
- [x] web.main_15m raises if profile != kalshi_crypto_15m_v2 (main)
- [x] web.main_legacy raises if profile == kalshi_crypto_15m_v2 (create_app)
- [x] Health endpoint is only `/api/health` on web.main_15m
- [x] Health response includes app="merid_15m_kalshi_crypto"
- [x] Health response includes profile="kalshi_crypto_15m_v2"
- [x] Health response includes loop.summary() (guarded)
- [x] Health response includes _startup_state["services"] (guarded)
- [x] Health endpoint never 500s (all exceptions caught)

---

## Test Cases

### Test 1: Wrong profile on main_15m
```bash
MERID_PROFILE=wrong_profile uvicorn web.main_15m:app --port 8011
# Expected: ValueError raised immediately
```

### Test 2: 15m profile on legacy main
```bash
MERID_PROFILE=kalshi_crypto_15m_v2 uvicorn web.main_legacy:app --port 8011
# Expected: ValueError raised immediately
```

### Test 3: Correct profile on main_15m
```bash
MERID_PROFILE=kalshi_crypto_15m_v2 uvicorn web.main_15m:app --port 8011
curl http://127.0.0.1:8011/api/health
# Expected: 200 with app="merid_15m_kalshi_crypto" and profile="kalshi_crypto_15m_v2"
```

### Test 4: Health endpoint tick/cycle_count increase
```bash
# Wait 10 seconds, hit health twice
curl http://127.0.0.1:8011/api/health | jq .loop.tick
# Wait 10 seconds
curl http://127.0.0.1:8011/api/health | jq .loop.tick
# Expected: tick increases by ~2 (5s cadence)
```
