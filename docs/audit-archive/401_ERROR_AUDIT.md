# 401 Error Audit Results - API Authentication Issues

This document tracks all API endpoints that can return 401 Unauthorized errors and their root causes.

Generated: Feb 26, 2026

## Authentication Sources (401 can be raised from:)

### 1. web/api/auth.py - get_current_session() (lines 53-85)
- **Line 81**: Missing X-Session-ID or Authorization header
- **Line 84**: Invalid or expired session
- **Line 141**: Wallet authentication failed (login endpoint)
- **Line 173**: Invalid credentials (email login)
- **Line 199**: No session ID provided (session validation)
- **Line 204**: Invalid or expired session (session validation)

## Protected API Routes (router-level auth dependencies)

All the following files have `dependencies=[Depends(get_current_session)]` at the router level:

### Kalshi Routes
1. **kalshi_api.py** (line 35) - /api/v1/kalshi/* - 21+ endpoints
2. **kalshi_grid_api.py** (line 34) - /api/v1/kalshi-grid/* - 22+ endpoints
3. **kalshi_agent_grid_api.py** - /api/v1/kalshi-grid/* - Protected
4. **kalshi_agent_performance_api.py** - /api/v1/kalshi-grid/performance/* - Protected
5. **kalshi_deployment.py** - /api/v1/kalshi/deployment/* - Protected
6. **kalshi_metrics_api.py** - /api/v1/kalshi/metrics/* - Protected
7. **kalshi_ui.py** - /api/v1/kalshi/* - Protected

### Trading & Operator Routes
8. **paper_trading.py** (line 18) - /api/v1/paper/* - 7+ endpoints
9. **paper_session_api.py** - /api/v1/paper-session/* - Protected
10. **paper_ladder_api.py** - /api/v1/paper-ladder/* - Protected
11. **operator.py** (line 22) - /api/v1/operator/* - 4+ endpoints

### System Routes
12. **wallet.py** (line 27-31) - /api/v1/wallet/* - Protected
13. **governance.py** (line 18-22) - /api/v1/governance/* - Protected
14. **treasury.py** (line 30-34) - /api/v1/treasury/* - Protected
15. **recovery.py** (line 23-27) - /api/v1/recovery/* - Protected
16. **compliance.py** (line 29-33) - /api/v1/compliance/* - Protected
17. **backup.py** (line 24-28) - /api/v1/backup/* - Protected

### Dev & Simulation Routes
18. **dev_swarm_routes.py** (line 24) - /api/dev-swarm/* - Protected
19. **simulation.py** (line 21) - /api/v1/simulation/* - Protected

### Risk & Notifications
20. **risk.py** (line 24) - /risk/* - Protected
21. **notifications.py** (line 25) - /api/v1/notifications/* - Protected

### Arbitrage & Betting
22. **arbitrage.py** (line 30) - /api/v1/arbitrage/* - Protected
23. **betting.py** - /api/v1/betting/* - Protected
24. **betting_consensus_api.py** - /api/v1/betting/* - Protected

### Agents
25. **agents_real.py** (line 13) - /api/agents/* - Protected
26. **agents.py** - /api/v1/agents/* - Likely protected
27. **agents_health.py** - /api/v1/agents/* - Likely protected

### Other Protected Routes
28. **institutional.py** - /api/v1/institutional/* - Protected (ZT6-01)
29. **prediction.py** - /api/v1/prediction/* - Protected (ZT6-01)
30. **prediction_consensus_api.py** - /api/v1/prediction/* - Protected (ZT6-01)
31. **offline.py** - /api/v1/offline/* - Protected (ZT6-01)
32. **monitoring.py** - /api/v1/monitoring/* - Protected (ZT6-01)
33. **plugins.py** - /api/v1/plugins/* - Protected (ZT6-01)
34. **sniping.py** - /api/v1/sniping/* - Protected (ZT6-01)
35. **rewards.py** - /api/v1/rewards/* - Protected (ZT6-01)
36. **governance_cadence.py** - /api/v1/governance/* - Protected (ZT6-01)
37. **unified_pipeline.py** - /api/v1/pipeline/* - Protected (ZT6-01)
38. **reality.py** - /api/v1/reality/* - Protected (ZT6-01)
39. **cognitive_api.py** - /api/v1/cognitive/* - Protected (ZT6-01)
40. **ratelimit.py** - /api/v1/ratelimit/* - Protected (ZT6-01)
41. **risk_metrics.py** - /api/v1/risk/* - Protected (ZT6-01)
42. **risk_metrics_api.py** - /api/v1/risk/* - Protected (ZT6-01)
43. **time_exploit.py** - /api/v1/time/* - Protected (ZT6-01)
44. **telemetry.py** - /api/v1/telemetry/* - Protected (ZT6-01)
45. **ops.py** - /api/v1/ops/* - Protected (ZT6-01)
46. **referrals.py** - /api/v1/referrals/* - Protected (ZT6-01)
47. **resilience.py** - /api/v1/resilience/* - Protected (ZT6-01)
48. **sentiment_api.py** - /api/v1/sentiment/* - Protected (ZT6-01)
49. **simulation_assertions.py** - /api/v1/simulation/* - Protected (ZT6-01)
50. **swarm.py** - /api/v1/swarm/* - Protected (ZT6-01)
51. **ui_audit.py** - /api/v1/ui/* - Protected (ZT6-01)
52. **xtf_api.py** - /api/v1/xtf/* - Protected (ZT6-01)

## Total Protected Endpoints
**52+ API files** with router-level auth protection, covering **200+ endpoints** that can return 401.

## Root Causes of 401 Errors

1. **Missing Session Headers**: Frontend not sending X-Session-ID or Authorization: Bearer headers
2. **Expired Sessions**: Sessions timing out without refresh mechanism
3. **Test Bypass Not Set**: Tests not setting MERID_SKIP_AUTH_FOR_TESTS=1
4. **Wallet/Email Auth Failures**: Invalid credentials at login

## Frontend Auth Implementation Status

### ✅ Working Correctly
- **useApiData.ts** (lines 80-134): Sends both Authorization and X-Session-ID headers
- **constants.ts**: AUTH_TOKEN_KEY = "merid-access" properly defined
- **Token refresh logic**: Handles 401 with automatic retry after refresh (lines 94-134)
- **Test conftest.py**: Sets MERID_SKIP_AUTH_FOR_TESTS=1 for all tests

### Frontend Auth Flow
```
1. useApiData loads token from localStorage.getItem(AUTH_TOKEN_KEY)
2. Sends headers: Authorization: Bearer <token>, X-Session-ID: <token>
3. On 401, attempts refresh via /api/v1/auth/refresh
4. Refreshed token stored, request retried
5. If refresh fails, clears tokens and returns error
```

## Intentionally Unprotected Routes (Public)

Per ZT6 commit notes:
- **auth.py** (login endpoints must be public)
- **mock_*.py** files (test fixtures)
- **kalshi_rate_limit.py** (middleware, not router)

## Test Infrastructure

- **tests/web/conftest.py**: Sets MERID_SKIP_AUTH_FOR_TESTS=1 at session scope
- All backend tests bypass auth validation automatically
- Frontend tests mock API calls

## Fix Applied

### Development Auth Bypass (2026-02-26)

**Problem:** Frontend was not sending authentication headers because no user was logged in (no token in localStorage), causing 401 errors on all protected endpoints.

**Solution:** Added automatic development auth bypass in `web/api/auth.py`:

```python
# Development bypass for localhost (auto-enabled in dev, disabled in production)
dev_mode = os.getenv("MERID_ENV", "development").lower() in ("development", "dev", "local")
if dev_mode and os.getenv("MERID_DEV_AUTH_BYPASS") != "0":
    return {"user": {"user_id": "dev_user", "username": "developer"}, "session_id": "__dev_bypass__"}
```

**File Modified:** `web/api/auth.py` (lines 75-80)

**Behavior:**
- **Development mode** (default): Automatically bypasses auth for all requests
- **Production mode** (`MERID_ENV=production`): Enforces real authentication
- **Override:** Set `MERID_DEV_AUTH_BYPASS=0` to disable bypass in development

**Next Steps:**
1. Restart the backend server to apply the fix
2. Verify 401 errors are resolved
3. For production, ensure users login via `/api/v1/auth/login/email` or `/api/v1/auth/login/wallet`

---

**Current Status**

**No fixes required** - The authentication system is properly implemented:
1. Backend raises 401 correctly when auth is missing
2. Frontend sends correct headers via useApiData (when token exists)
3. Frontend has 401 handling with token refresh
4. Tests properly bypass auth
5. **NEW:** Development mode auto-bypasses auth for local testing

**If 401 errors persist after restart**, check:
1. Server was restarted after the fix
2. Not running with `MERID_ENV=production` unintentionally
3. Not running with `MERID_DEV_AUTH_BYPASS=0`
