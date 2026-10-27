# Kalshi Environment Setup Guide

This document provides the required environment variables and configuration for running MERID with Kalshi integration in both production and demo environments.

## Environment Separation

Kalshi requires strict separation between production and demo environments. Each environment uses different base URLs and credentials.

### Production Environment

**Base URLs:**
- REST API: `https://external-api.kalshi.com/trade-api/v2`
- WebSocket: `wss://external-api-ws.kalshi.com/trade-api/ws/v2`

**Required Environment Variables:**

```bash
# Environment selection
MERID_KALSHI_ENV=prod  # or unset (defaults to prod)

# Kalshi Production Credentials (API Key + Private Key - newer format)
KALSHI_LIVE_API_KEY_ID=your_live_api_key_id
KALSHI_LIVE_PRIVATE_KEY_PATH=/path/to/your/kalshi_private_key.pem

# Alternative: Email + Password + API Key Secret (older format)
KALSHI_EMAIL=your_email@example.com
KALSHI_PASSWORD=your_password
KALSHI_API_KEY_SECRET=your_api_key_secret

# Profile configuration
MERID_PROFILE=kalshi_crypto_15m_v2

# Security settings
MERID_ALLOW_FAKE_BANKROLL_FOR_TEST=0  # MUST be 0 or unset in production

# Bankroll service timeouts (optional, defaults to 45s)
MERID_BANKROLL_EQUITY_TIMEOUT_S=45
MERID_BANKROLL_SUMMARY_TIMEOUT_S=45

# Server configuration
PORT=8011
```

### Demo/Sandbox Environment

**Base URLs:**
- REST API: `https://external-api.demo.kalshi.co/trade-api/v2`
- WebSocket: `wss://external-api-ws.demo.kalshi.co/trade-api/ws/v2`

**Required Environment Variables:**

```bash
# Environment selection
MERID_KALSHI_ENV=demo

# Kalshi Demo Credentials
KALSHI_DEMO_API_KEY_ID=your_demo_api_key_id
KALSHI_DEMO_PRIVATE_KEY_PATH=/path/to/your/kalshi_demo_private_key.pem

# Profile configuration (use test profile, NOT kalshi_crypto_15m_v2)
MERID_PROFILE=kalshi_crypto_15m_test

# Security settings (may be 1 for test profiles)
MERID_ALLOW_FAKE_BANKROLL_FOR_TEST=1  # Only for test profiles

# Server configuration
PORT=8011
```

## Environment Resolution Priority

The system resolves the Kalshi environment in the following order:

1. `MERID_KALSHI_ENV` (highest priority)
2. `KALSHI_ENV` (legacy, lower priority)
3. `"prod"` (default if neither is set)

## Live Profile Classification

The `is_live_profile()` function in `merid/risk/profiles/crypto_15m_profile.py` classifies profiles as live trading profiles based on:

1. **Profile name**: Must be `kalshi_crypto_15m_v2`
2. **Environment**: Must be `prod` (not `demo`)
3. **Fake bankroll flag**: `MERID_ALLOW_FAKE_BANKROLL_FOR_TEST` must be `0` or unset

If any of these conditions fail, the profile is considered non-live and may use demo/fake bankroll under explicit flags.

## Bankroll API Endpoint

The canonical bankroll source is Kalshi's production `/portfolio/balance` endpoint:

```
GET /trade-api/v2/portfolio/balance
```

### Example Request

```bash
curl -X GET "https://external-api.kalshi.com/trade-api/v2/portfolio/balance" \
  -H "KALSHI-API-KEY-ID: your_api_key_id" \
  -H "KALSHI-PRIVATE-KEY: your_signature"
```

### Example Response

```json
{
  "balance": 100000,           // Balance in cents ($1000.00)
  "locked_balance": 5000,     // Locked balance in cents ($50.00)
  "portfolio_value": 200000    // Portfolio value in cents ($2000.00)
}
```

**Units:**
- All monetary values are in **cents** (integers)
- Internal system converts to **USD** (Decimal) for calculations
- 100 cents = $1.00 USD

### Response Format Validation

The system enforces strict response format validation:

1. **Flat format only**: Rejects nested/unknown formats
2. **Non-negative values**: Raises `ValueError` on negative balances
3. **Type validation**: Ensures numeric values can be converted to Decimal

## Fail-Closed Behavior

In production (live profiles), the bankroll service follows fail-closed behavior:

- If bankroll is `ERROR` or `UNKNOWN` state → trading blocked
- If API timeout or failure → returns `None` from `get_equity_for_risk_calc_sync()`
- No automatic fallbacks to config or paper balances
- Explicit error logging for troubleshooting

## Startup Sequence

The bankroll service initializes during startup with the following sequence:

1. **Phase 1.7**: Bankroll service initialization
   - Import `bankroll_service_v2`
   - Call `get_bankroll_service()` singleton
   - Call `bankroll.start()` with 10s initial fetch timeout
   - Register equity provider with `GlobalRiskGuard`

2. **Timeout Handling**:
   - Default timeout: 45s (configurable via `MERID_BANKROLL_EQUITY_TIMEOUT_S`)
   - If initial fetch times out → service starts in `ERROR` state
   - If initial fetch succeeds → service starts in `FRESH` state

3. **State Transitions**:
   - `UNKNOWN` → `FRESH` on successful initial fetch
   - `FRESH` → `ERROR` on persistent failures
   - `ERROR` → `FRESH` on successful recovery

## Port Configuration

The default server port is `8011`. This can be configured via:

```bash
PORT=8011  # Default
```

**Port Conflict Handling:**
- On Windows, port conflicts (WinError 10048) are logged as server/OS issues
- The process shuts down cleanly on bind failure
- Bankroll service does not continue running after shutdown starts

## Verification Checklist

Before deploying to production, verify:

- [ ] `MERID_KALSHI_ENV=prod` (or unset)
- [ ] `MERID_PROFILE=kalshi_crypto_15m_v2`
- [ ] `MERID_ALLOW_FAKE_BANKROLL_FOR_TEST=0` (or unset)
- [ ] Production credentials configured (`KALSHI_LIVE_API_KEY_ID`, `KALSHI_LIVE_PRIVATE_KEY_PATH`)
- [ ] No `MERID_DEMO_MODE` in environment
- [ ] Port 8011 is available
- [ ] Bankroll service reaches `FRESH` state within 45s
- [ ] Risk envelope is populated with live bankroll
- [ ] No demo URLs in logs or configuration

## Troubleshooting

### Bankroll Service Timeout

If bankroll service fails to reach `FRESH` state:

1. Check Kalshi API credentials are valid
2. Verify network connectivity to `external-api.kalshi.com`
3. Check `MERID_BANKROLL_EQUITY_TIMEOUT_S` if on slow connection
4. Review logs for `[BANKROLL-STARTUP-SUMMARY]` messages

### Port Conflict

If port 8011 is already in use:

1. Check for existing MERID processes: `netstat -ano | findstr :8011`
2. Kill conflicting process or change `PORT` environment variable
3. Verify no other services using port 8011

### Environment Misconfiguration

If profile classification fails:

1. Verify `MERID_PROFILE=kalshi_crypto_15m_v2`
2. Verify `MERID_KALSHI_ENV=prod`
3. Verify `MERID_ALLOW_FAKE_BANKROLL_FOR_TEST=0`
4. Check logs for profile classification errors

## Additional Resources

- [Kalshi API Documentation](https://docs.kalshi.com)
- [Kalshi Quick Start](https://docs.kalshi.com/getting_started/quick_start_authenticated_requests)
- [Kalshi API Keys](https://docs.kalshi.com/getting_started/api_keys)
- [Kalshi Demo Environment](https://docs.kalshi.com/getting_started/demo_env)
- [Kalshi Portfolio API](https://docs.kalshi.com/margin-rest/portfolio/get-balance)
