# 15m Lean Stack Runbook

**Operational Guide for Running and Verifying the 15m Kalshi Production Stack**

This runbook answers "how do I safely run this in live mode and know it's healthy?"

---

## Prerequisites

### Environment Variables

Set the following in `.env` for production deployment:

```bash
# Profile (required)
MERID_PROFILE=kalshi_crypto_15m_v2

# Trading mode (required)
MERID_TRADING_MODE=demo          # or "live" for production
TRADING_ENABLED=false            # set to true to enable trading

# Kalshi credentials (required for live mode)
KALSHI_API_KEY_ID=your_key_id
KALSHI_PRIVATE_KEY_PATH=path/to/private_key.pem
KALSHI_USE_DEMO=false            # false for live mode

# UnifiedEdgeConfig variables (required)
UNIFIED_EDGE_CONFIG_PATH=config/unified_edge_config.yaml

# Optional: Spot price service configuration
SPOT_PRICE_SERVICE_URL=https://api.example.com/spot
```

### Mode Flags

The `is_demo` and `is_live` flags in `KalshiVenueClient` and `BankrollServiceV2` are derived from the configuration:

- **`is_demo`**: True if `KALSHI_USE_DEMO=true` or `MERID_TRADING_MODE=demo`
- **`is_live`**: True if `KALSHI_USE_DEMO=false` and `MERID_TRADING_MODE=live`

**Verification:**
```python
from merid.event_venues.kalshi.client import KalshiVenueClient
from merid.event_venues.kalshi.config import KalshiConfig

config = KalshiConfig(use_demo=False)
client = KalshiVenueClient(config=config)

assert client.is_demo == False
assert client.is_live == True
```

Both flags cannot be true simultaneously. The `/api/v1/self-check` endpoint validates this invariant.

---

## Startup Procedure

### Step 1: Start the Application

```bash
# Set environment variables
export MERID_PROFILE=kalshi_crypto_15m_v2
export MERID_TRADING_MODE=demo
export TRADING_ENABLED=false

# Start uvicorn
uvicorn web.main_15m_lean:app --host 0.0.0.0 --port 8000
```

### Step 2: Trigger Startup

Call `/api/v1/health` once to trigger startup. This is the only startup trigger.

```bash
curl http://localhost:8000/api/v1/health
```

Expected response (before startup completes):
```json
{
  "status": "ok",
  "api_version": "15m_v2",
  "health_impl": "health_v3_20260530_0940",
  "health_debug": "main_15m_lean_v4_1015",
  "startup_started": true,
  "startup_completed": false,
  "startup_failed": false,
  "error": null,
  "started_at": "2026-05-30T14:00:00Z",
  "completed_at": null
}
```

### Step 3: Wait for Startup Completion

Poll `/api/v1/health` until `startup_completed` is true. Startup typically takes 60-120 seconds.

```bash
# Wait for startup (simple polling script)
while true; do
  response=$(curl -s http://localhost:8000/api/v1/health)
  completed=$(echo $response | jq -r '.startup_completed')
  if [ "$completed" = "true" ]; then
    echo "Startup completed"
    break
  fi
  echo "Waiting for startup..."
  sleep 5
done
```

### Step 4: Verify Health with Self-Check

Call `/api/v1/self-check` to verify all invariants pass.

```bash
curl http://localhost:8000/api/v1/self-check
```

See **Health Checks** section below for expected response.

---

## Health Checks

### `/api/v1/self-check` Validation

The self-check endpoint must show all sections passing:

```json
{
  "profile": {
    "name": "kalshi_crypto_15m_v2",
    "env": "production",
    "expected": "kalshi_crypto_15m_v2",
    "valid": true
  },
  "mode": {
    "is_demo": false,
    "is_live": true,
    "consistent": true
  },
  "startup": {
    "completed": true,
    "trading_enabled": false
  },
  "components": {
    "agent_grid_15m": true,
    "loop_15m": true,
    "bankroll": true,
    "kalshi_client": true
  },
  "legacy": {
    "modules_loaded": [],
    "count": 0
  },
  "invariants": {
    "all_passed": true,
    "checks": {
      "profile_and_env": {"passed": true, "message": "Profile is kalshi_crypto_15m_v2"},
      "no_legacy_subsystems": {"passed": true, "message": "No legacy modules loaded"},
      "startup_state": {"passed": true, "message": "Startup completed successfully"},
      "app_state_components": {"passed": true, "message": "All components present"},
      "unified_edge_config": {"passed": true, "message": "UnifiedEdgeConfig valid"},
      "agent_config_consistency": {"passed": true, "message": "Agent config OK: ['BTC_15M', 'ETH_15M', 'SOL_15M', 'XRP_15M', 'DOGE_15M']"}
    }
  }
}
```

**Section validation:**
- **profile**: `name` must be `kalshi_crypto_15m_v2`, `valid` must be `true`
- **mode**: `is_live` should be `true` for production, `consistent` must be `true`
- **startup**: `completed` must be `true`, `trading_enabled` depends on your intent
- **components**: All must be `true` (agent_grid_15m, loop_15m, bankroll, kalshi_client)
- **legacy**: `modules_loaded` must be empty array, `count` must be `0`
- **invariants**: `all_passed` must be `true`, all individual checks must pass

### HTTP Status Codes

- **200 OK**: All invariants pass, system is healthy
- **503 Service Unavailable**: One or more invariants failed, check response body for details

---

## End-to-End Live Verification

### Verify 5 Agents are Enabled

```bash
curl http://localhost:8000/api/v1/agents
```

Expected response:
```json
{
  "schema_version": "1.0.0",
  "initialized": true,
  "agents": [
    {"name": "BTC_15M", "enabled": true, ...},
    {"name": "ETH_15M", "enabled": true, ...},
    {"name": "SOL_15M", "enabled": true, ...},
    {"name": "XRP_15M", "enabled": true, ...},
    {"name": "DOGE_15M", "enabled": true, ...}
  ],
  "summary": {
    "total": 5,
    "enabled": 5,
    "disabled": 0,
    "zombies": 0
  }
}
```

**Validation:**
- `total` must be `5`
- `enabled` must be `5`
- `disabled` must be `0`
- `zombies` must be `0` (no agents without recent signals)
- All 5 agent names must be present

### Verify Bankroll and Risk Caps

```bash
curl http://localhost:8000/api/v1/risk-snapshot
```

Expected response:
```json
{
  "schema_version": "1.0.0",
  "initialized": true,
  "bankroll": {
    "equity_usd": 10000.00,
    "available_cash_usd": 8500.00,
    "open_pnl_usd": 1500.00
  },
  "risk_env": {
    "per_asset_caps": {
      "BTC": {"max_notional_usd": 2000, "current_notional_usd": 500},
      "ETH": {"max_notional_usd": 2000, "current_notional_usd": 300},
      "SOL": {"max_notional_usd": 2000, "current_notional_usd": 0},
      "XRP": {"max_notional_usd": 2000, "current_notional_usd": 0},
      "DOGE": {"max_notional_usd": 2000, "current_notional_usd": 0}
    },
    "global_caps": {
      "max_total_notional_usd": 10000,
      "current_total_notional_usd": 800
    },
    "utilization": {
      "BTC": 0.25,
      "ETH": 0.15,
      "SOL": 0.0,
      "XRP": 0.0,
      "DOGE": 0.0
    }
  }
}
```

**Validation:**
- `bankroll.equity_usd` should match your Kalshi account balance
- `bankroll.available_cash_usd` should be positive
- All 5 assets should have per-asset caps
- `global_caps.max_total_notional_usd` should match your risk policy
- Utilization should be reasonable (< 1.0 for all assets)

### Verify Loop Status

```bash
curl http://localhost:8000/api/v1/loop-status
```

Expected response:
```json
{
  "status": "running",
  "running": true,
  "last_cycle_at": "2026-05-30T14:05:00Z",
  "cycle_duration_ms": 150,
  "error_count": 0
}
```

**Validation:**
- `status` should be `running` (or `starting` immediately after startup)
- `running` should be `true`
- `last_cycle_at` should be recent (within last 15 minutes)
- `cycle_duration_ms` should be reasonable (< 5000ms)
- `error_count` should be low (< 10)

### Match Live Trades in Kalshi UI

1. Log into Kalshi production UI
2. Navigate to Positions and Orders
3. Verify:
   - Open positions match `/api/v1/agents` open position counts
   - Fills match bankroll state in `/api/v1/risk-snapshot`
   - Total notional matches `risk_env.global_caps.current_total_notional_usd`

---

## Safe Shutdown

### Graceful Shutdown

The 15m lean stack uses FastAPI's shutdown hooks for graceful cleanup. Send SIGTERM to the uvicorn process:

```bash
# If running with uvicorn directly
kill -TERM <pid>

# If running with systemd
systemctl stop merid-15m-lean

# If running with Docker
docker stop merid-15m-lean
```

### Expected Shutdown Logs

Watch logs for the following sequence:

1. **Loop stop**: `[LOOP-15M] Stopping execution loop`
2. **WebSocket close**: `[WS-BRIDGE] Closing WebSocket connection`
3. **WS refresh supervisor stop**: `[WS-REFRESH] Stopping refresh supervisor`
4. **Bankroll cleanup**: `[BANKROLL] Saving bankroll state`
5. **Application shutdown**: `Application shutdown complete`

### Force Shutdown (Emergency)

If graceful shutdown hangs, use SIGKILL:

```bash
kill -9 <pid>
```

**Warning**: This may leave:
- Unclosed WebSocket connections
- Unsaved bankroll state
- Incomplete position updates

Verify state after force shutdown by calling `/api/v1/self-check` on restart.

---

## Troubleshooting

### Startup Fails

**Symptom**: `/api/v1/health` shows `startup_failed: true`

**Check**:
1. Review logs for error message in `startup_state.error`
2. Verify Kalshi credentials are correct
3. Check network connectivity to Kalshi API
4. Verify UnifiedEdgeConfig file exists and is valid
5. Check `/api/v1/self-check` for specific invariant failures

**Common causes**:
- Invalid Kalshi credentials
- Network connectivity issues
- Missing or invalid UnifiedEdgeConfig
- Profile mismatch (not `kalshi_crypto_15m_v2`)

### Legacy Modules Loaded

**Symptom**: `/api/v1/self-check` shows `legacy.modules_loaded` non-empty

**Check**:
1. Review the list of loaded modules
2. Verify no imports of PaperSession, AgentRegistry, or ReflectionSystem in lean stack files
3. Check for accidental imports in dependencies

**Resolution**:
- Remove legacy imports from affected files
- Restart application

### Agents Not Starting

**Symptom**: `/api/v1/agents` shows fewer than 5 enabled agents

**Check**:
1. Verify `config/kalshi_agent_grid.yaml` has exactly 5 enabled agents
2. Check `/api/v1/self-check` agent_config_consistency check
3. Review agent grid initialization logs

**Resolution**:
- Fix agent grid configuration
- Restart application

### Loop Not Running

**Symptom**: `/api/v1/loop-status` shows `status: stopped` or `status: error`

**Check**:
1. Verify `TRADING_ENABLED` is set to `true` if you want trading
2. Review loop logs for errors
3. Check `error_count` in `/api/v1/loop-status`

**Resolution**:
- Fix loop configuration
- Restart application
- If error_count > 10, investigate error logs

### Bankroll Mismatch

**Symptom**: Bankroll in `/api/v1/risk-snapshot` doesn't match Kalshi UI

**Check**:
1. Verify Kalshi credentials are for the correct environment (demo vs live)
2. Check bankroll refresh timestamp
3. Review bankroll service logs for API errors

**Resolution**:
- Force bankroll refresh (if endpoint available)
- Restart application
- Verify Kalshi API is accessible

---

## Monitoring

### Key Metrics to Monitor

1. **Startup health**: `/api/v1/health` - startup_completed should be true
2. **Invariants**: `/api/v1/self-check` - all_passed should be true
3. **Agent health**: `/api/v1/agents` - zombies should be 0
4. **Loop health**: `/api/v1/loop-status` - error_count should be low
5. **Bankroll**: `/api/v1/risk-snapshot` - utilization should be reasonable

### Alerting Thresholds

Consider alerting on:
- `startup_failed: true` - critical
- `invariants.all_passed: false` - critical
- `legacy.count > 0` - critical
- `agents.zombies > 0` - warning
- `loop_status.error_count > 10` - warning
- `loop_status.status: error` - critical
- `risk_env.utilization > 0.8` for any asset - warning

### Log Levels

Key log prefixes to monitor:
- `[STARTUP]` - Startup phase logs
- `[LOOP-15M]` - Execution loop logs
- `[WS-BRIDGE]` - WebSocket bridge logs
- `[BANKROLL]` - Bankroll service logs
- `[AGENT-GRID]` - Agent grid logs
- `[RISK]` - Risk management logs

---

## Related Documentation

- [`docs/15m_lean_stack.md`](15m_lean_stack.md) - Architecture documentation
- [`docs/legacy_overview.md`](legacy_overview.md) - Legacy systems documentation
- [`merid/kalshi_15m_runtime_check.py`](../merid/kalshi_15m_runtime_check.py) - Runtime invariants implementation
- [`README.md`](../README.md) - Project README
