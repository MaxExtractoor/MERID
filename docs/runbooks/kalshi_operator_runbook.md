# Kalshi Operator Runbook — MERID Production Operations

**Version:** 1.0  
**Last Updated:** 2026-03-28  
**Scope:** Kalshi-only production trading operations

---

## Quick Reference

| Component | Health Endpoint | Critical Metric |
|-----------|-----------------|-----------------|
| Kalshi REST | `GET /api/v1/kalshi/health` | `circuit_open: false` |
| Kalshi WS | `GET /api/v1/kalshi/ws` | `connected: true` |
| Fills Ledger | `GET /api/v1/kalshi/fills` reconciliation | `status: "ok"` |
| RTI Buffer | `GET /api/v1/rti-feed/status` | `filled_count == 60` |
| CT Trader | `GET /api/v1/continuous-trader/status` | `is_running: true` |
| Agent Grid | `GET /api/v1/kalshi-grid/agents` | `agents > 0` |

---

## Scenario 1: Normal Trading

### Symptoms
- All health checks return OK
- PnL updating normally
- Orders filling as expected

### Operator Actions
1. **Verify health baseline** (every 15 min during active trading):
   ```bash
   curl http://localhost:8011/api/v1/kalshi/health | jq '.status'
   # Expected: "healthy"
   ```

2. **Check fills ledger reconciliation**:
   ```bash
   curl http://localhost:8011/api/v1/kalshi/health | jq '.fills_ledger.reconciliation.status'
   # Expected: "ok"
   ```

3. **Monitor RTI buffer** (for 15m/hourly positions):
   ```bash
   curl http://localhost:8011/api/v1/rti-feed/status | jq '.buffers.BTC.filled_count'
   # Expected: 60 (or increasing toward 60 near expiry)
   ```

4. **Review recent fills**:
   ```bash
   curl http://localhost:8011/api/v1/kalshi/fills?limit=10
   ```

---

## Scenario 2: Partial API Hiccup (Kalshi REST degraded)

### Symptoms
- `GET /api/v1/kalshi/health` shows `circuit_open: true`
- Orders may be queued or failing
- Error rate elevated

### Operator Actions

1. **Confirm circuit state**:
   ```bash
   curl http://localhost:8011/api/v1/kalshi/health | jq '.circuit_breaker'
   ```

2. **Check if circuit is recovering**:
   ```bash
   curl http://localhost:8011/api/v1/kalshi/health | jq '.circuit_breaker.time_until_retry'
   # If < 30s, wait for auto-recovery
   ```

3. **If circuit stuck open (> 2 min)**:
   - Check Kalshi status: https://status.kalshi.com
   - Verify credentials: `KALSHI_API_KEY_ID`, `KALSHI_PRIVATE_KEY_PATH`
   - Restart CT trader: `POST /api/v1/continuous-trader/stop` then restart

4. **Verify fills ledger is still consistent**:
   ```bash
   curl http://localhost:8011/api/v1/kalshi/health | jq '.fills_ledger.reconciliation'
   ```

---

## Scenario 3: Full Kalshi Outage

### Symptoms
- All Kalshi endpoints returning 5xx or timeout
- Circuit breaker open on all paths
- WebSocket disconnected

### Operator Actions

1. **Immediate: Activate kill switch**:
   ```bash
   curl -X POST http://localhost:8011/api/v1/kalshi/kill-switch \
     -H "Content-Type: application/json" \
     -d '{"reason": "Kalshi outage - full stop"}'
   ```

2. **Verify no new orders can be placed**:
   - Check `KalshiGridView` — mode should show "BLOCKED"
   - Attempt test order — should be rejected

3. **Preserve state**:
   - Fills ledger persists automatically to SQLite
   - Paper state (if applicable) in `data/paper_positions.json`

4. **Monitor for recovery**:
   - Check https://status.kalshi.com every 5 minutes
   - When Kalshi reports healthy, verify with:
     ```bash
     curl http://localhost:8011/api/v1/kalshi/health
     ```

5. **Resume trading** (when Kalshi is confirmed healthy):
   - Reset kill switch: `POST /api/v1/kalshi/kill-switch/reset`
   - Verify reconciliation passes
   - Restart CT trader if needed
   - Start with small canary trade

---

## Scenario 4: RTI Buffer Delay (Settlement Risk)

### Symptoms
- `GET /api/v1/rti-feed/status` shows `filled_count < 60`
- Positions approaching expiry (within 5 minutes)
- Risk alerts for "incomplete settlement buffer"

### Operator Actions

1. **Check buffer status**:
   ```bash
   curl http://localhost:8011/api/v1/rti-feed/buffer/BTC | jq '.filled_count, .status'
   ```

2. **If `status: "incomplete"` AND expiry < 2 minutes**:
   - System should auto-block new buys (strict mode)
   - Verify: `GET /api/v1/kalshi/risk` — `settlement_guard_active: true`

3. **If strict mode not activating** (manual intervention needed):
   - Activate kill switch for affected asset
   - Review `merid/event_venues/kalshi/settlement_execution_guard.py` logs

4. **Post-expiry**:
   - Verify settlement price used matches CF Benchmarks
   - Check `POST /api/v1/kalshi/prob-accuracy/record` for resolution data

---

## Scenario 5: No Tradeable Markets (System Up)

### Symptoms
- Kalshi health OK
- No markets pass filters (edge, expiry, etc.)
- CT trader running but no activity

### Operator Actions

1. **Verify market catalog is populated**:
   ```bash
   curl http://localhost:8011/api/v1/kalshi/catalog | jq '.total_markets'
   ```

2. **Check filter pipeline**:
   - Review `KalshiContinuousTrader` logs for filter rejections
   - Common causes:
     - Edge too low (`min_edge` threshold)
     - Contract price too high (`max_contract_price_cents`)
     - Too close to expiry (`settlement_guard_seconds`)

3. **Adjust if needed** (with caution):
   - Modify `TraderConfig` via environment (requires restart)
   - Or manually place order via Terminal for specific opportunity

4. **Not a system failure** — this is normal when no good opportunities exist

---

## Log Patterns to Grep

### Critical Errors (immediate action required)
```bash
# Auth failures
powershell -Command "Select-String -Path logs/merid.log -Pattern 'auth error|401|403'"

# Circuit breaker open
grep "Circuit OPEN" logs/merid.log

# Fills reconciliation broken
grep "reconciliation.*broken|divergence.*critical" logs/merid.log

# Settlement guard violation
grep "settlement.*incomplete|RTI.*buffer.*fail" logs/merid.log
```

### Warning Patterns (monitor closely)
```bash
# Rate limiting
grep "rate-limited|429" logs/merid.log

# Partial fills
grep "partial.*fill|fill.*ratio" logs/merid.log

# WebSocket reconnect
grep "WS.*reconnect|WebSocket.*error" logs/merid.log
```

### Info Patterns (normal operations)
```bash
# Successful orders
grep "order.*placed|order.*filled" logs/merid.log

# Reconciliation OK
grep "reconciliation.*OK|Reconciliation OK" logs/merid.log
```

---

## Key Environment Variables to Verify

### Critical for Live Trading
| Variable | Expected Value | Verification |
|----------|---------------|--------------|
| `KALSHI_API_KEY_ID` | Valid UUID | `echo $KALSHI_API_KEY_ID` |
| `KALSHI_PRIVATE_KEY_PATH` | Path to `.pem` file | `ls -la $KALSHI_PRIVATE_KEY_PATH` |
| `KALSHI_USE_DEMO` | `false` for live | `echo $KALSHI_USE_DEMO` |
| `MERID_PM_LIVE_ENABLED` | `true` for live | `echo $MERID_PM_LIVE_ENABLED` |
| `MERID_LIVE_TRADING_UNLOCKED` | `true` for live | `echo $MERID_LIVE_TRADING_UNLOCKED` |
| `MERID_TRADING_MODE` | `live` for live | `echo $MERID_TRADING_MODE` |

### Quick Verification Script
```bash
#!/bin/bash
echo "=== Kalshi Trading Environment ==="
echo "KALSHI_USE_DEMO: $KALSHI_USE_DEMO (should be 'false' for live)"
echo "MERID_TRADING_MODE: $MERID_TRADING_MODE (should be 'live' for live)"
echo "MERID_PM_LIVE_ENABLED: $MERID_PM_LIVE_ENABLED (should be 'true' for live)"
echo "MERID_LIVE_TRADING_UNLOCKED: $MERID_LIVE_TRADING_UNLOCKED (should be 'true' for live)"

# Key file check
if [ -f "$KALSHI_PRIVATE_KEY_PATH" ]; then
    echo "✓ Private key file exists"
else
    echo "✗ Private key file NOT FOUND at $KALSHI_PRIVATE_KEY_PATH"
fi
```

---

## Tabletop Exercises

### Tabletop 1: Circuit Breaker Storm
**Setup:** Simulated 5xx errors from Kalshi  
**Objective:** Verify system throttles, recovers, doesn't hammer API  
**Success Criteria:**
- Circuit opens within 10 failures
- No more than 1 request per 30s while open
- Auto-recovery after timeout
- All fills eventually reconciled

### Tabletop 2: RTI Feed Outage During Final Minute
**Setup:** RTI buffer stops updating 30s before expiry  
**Objective:** Verify strict settlement guard blocks trades  
**Success Criteria:**
- `settlement_guard_active: true` within 5s of buffer stall
- New buy orders rejected
- Existing positions can be reduced
- Alert sent to operator

### Tabletop 3: Fill Reconciliation Divergence
**Setup:** Simulated missing fill in ledger  
**Objective:** Verify reconciliation detects and alerts  
**Success Criteria:**
- Reconciliation status changes to `degraded` or `broken`
- Divergence quantified in health endpoint
- Alert notification sent
- Manual reconciliation process documented

---

## Emergency Contacts & Resources

| Resource | URL/Command |
|----------|-------------|
| Kalshi Status | https://status.kalshi.com |
| Kalshi API Docs | https://docs.kalshi.com |
| CF Benchmarks | https://docs.cfbenchmarks.com |
| MERID Health | `curl http://localhost:8011/api/v1/kalshi/health` |
| Kill Switch | `POST /api/v1/kalshi/kill-switch` |
| Fills Export | `GET /api/v1/kalshi/export` |

---

## Change Log

| Date | Version | Changes |
|------|---------|---------|
| 2026-03-28 | 1.0 | Initial runbook for Kalshi-only audit |

---

*This runbook is tied to the tabletop scenarios in `docs/KALSHI_STAGING_TABLETOP_SCENARIOS.md`.*
