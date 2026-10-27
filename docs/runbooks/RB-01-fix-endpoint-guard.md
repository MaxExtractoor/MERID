# RB-1: FIX Endpoint Guard Trip (403)

**Alert:** `merid_guard_trips_total{guard_type="FIX_ENDPOINT",mode="live"} > 0`

## Symptoms

- Client receives HTTP **403 Forbidden** on `/api/v1/kalshi/fix/orders`
- Log entry: `{"event_type": "GUARD_TRIP", "guard": "PASS8_FIX_GUARD"}`
- Response body includes: `"error": "GUARD_TRIP_FIX_ENDPOINT_BLOCKED"`

## Impact

- Order **rejected** - no trade executed
- Client must use canonical executor endpoint
- No funds at risk (guard working as designed)

## Investigation

### 1. Check Recent Guard Trips

```bash
# View recent FIX guard trips
grep "GUARD_TRIP.*PASS8_FIX_GUARD" /var/log/merid/app.log | tail -20

# Or with jq if logs are JSON
jq 'select(.guard == "PASS8_FIX_GUARD")' /var/log/merid/app.log | tail -5
```

### 2. Identify Source

```bash
# Check source IP and client details
jq 'select(.guard == "PASS8_FIX_GUARD") | {timestamp, mode, endpoint, source, details}' \
  /var/log/merid/app.log | tail -1
```

### 3. Review Access Pattern

```bash
# Check if isolated incident or pattern
grep "PASS8_FIX_GUARD" /var/log/merid/app.log | wc -l
# If > 5 in short period, possible attack or misconfigured client
```

## Remediation

### Case A: Accidental Legacy Client Usage

**If:** Client is legitimate but using old endpoint

1. **Immediate:** Update client configuration
   ```python
   # Change from:
   POST /api/v1/kalshi/fix/orders
   
   # To:
   POST /api/v1/kalshi/orders
   ```

2. **Verify fix works:**
   ```bash
   curl -X POST http://localhost:8000/api/v1/kalshi/orders \
     -H "Authorization: Bearer $TOKEN" \
     -H "Content-Type: application/json" \
     -d '{
       "ticker": "KXBTC-15M",
       "side": "buy",
       "quantity": 1,
       "price": 5000
     }'
   # Expected: 200 OK or risk rejection (not 403)
   ```

### Case B: Potential Bypass Attempt

**If:** Suspicious pattern or unknown client

1. **Immediate:** No action needed (guard blocked it)

2. **Investigate:**
   - Check access logs for IP reputation
   - Review authentication tokens used
   - Cross-reference with known clients

3. **If malicious:**
   ```bash
   # Rotate compromised credentials
   python scripts/rotate_credentials.py --client-id <ID>
   
   # Block IP if necessary
   iptables -A INPUT -s <SUSPICIOUS_IP> -j DROP
   ```

### Case C: Legacy System Migration

**If:** Intentional use by legacy system needing migration

1. **Schedule migration:** Move system to `/api/v1/kalshi/orders`
2. **Temporary:** If urgent, legacy system can use SIM mode for testing:
   ```bash
   export MERID_TRADE_MODE=sim
   ```

## Verification

```bash
# 1. Confirm canonical endpoint works
curl -X POST /api/v1/kalshi/orders -d '{...}' | jq .status
# Expected: "submitted" or "rejected_by_risk" (not 403)

# 2. Confirm FIX endpoint still blocked in live
export MERID_TRADE_MODE=live
curl -X POST /api/v1/kalshi/fix/orders -d '{...}'
# Expected: 403 Forbidden

# 3. Check metrics
curl http://localhost:9100/metrics | grep merid_guard_trips_total
# Should show counter incremented
```

## Escalation

**Contact:** #risk-engineering if:
- > 5 guard trips in 5 minutes (possible attack)
- Unknown client source
- Repeated attempts after notification

**Do not disable the guard** - this is a critical safety control.

## Related

- Guard location: `web/api/kalshi_api.py:5970`
- Test: `tests/scenario/test_pass9_scenarios.py::test_fix_endpoint_blocked_in_live`
- CI Invariant: `check_fix_endpoint_guard()`
