# KalshiSettlementPoller Live Verification Guide

## Overview

The KalshiSettlementPoller is a critical background service that:
- Polls Kalshi's `GET /portfolio/settlements` endpoint for newly settled markets
- Fires settlement hooks in `merid/reconciliation.py` to record realized PnL
- Updates the CT bankroll invariant via `ct.record_trade_result(pnl_cents)`
- Uses cursor-based pagination to ensure no settlements are missed across restarts

## Quick Verification

### Option 1: Using the verification script

```bash
# Single check
python scripts/verify_settlement_poller.py

# Watch mode (updates every 10 seconds)
python scripts/verify_settlement_poller.py --watch

# Check remote server
python scripts/verify_settlement_poller.py --host production.example.com --port 8000
```

### Option 2: Using curl

```bash
# Detailed settlement poller status
curl http://localhost:8000/health/settlement_poller | jq

# Global health including settlement poller
curl http://localhost:8000/api/health | jq '.checks.settlement_poller'

# Startup status (all services)
curl http://localhost:8000/startup | jq '.services.kalshi_settlement_poller'
```

## API Endpoints

### GET /health/settlement_poller

**Response Fields:**
- `status`: "running", "stopped", "not_configured", or "error"
- `health`: "healthy", "inactive", or "unknown"
- `running`: boolean - true if the poll loop is active
- `poll_count`: number of polls executed since start
- `settlement_count`: number of settlements processed
- `last_cursor`: most recent cursor value (null if no polls yet)
- `seen_ids_count`: number of settlement IDs in deduplication cache
- `cursor_history_len`: number of cursor checkpoints saved in Redis
- `timestamp`: current server time

**Example Response (Running):**
```json
{
  "status": "running",
  "health": "healthy",
  "running": true,
  "poll_count": 142,
  "settlement_count": 7,
  "last_cursor": "abc123def456",
  "seen_ids_count": 7,
  "cursor_history_len": 7,
  "timestamp": 1712293453.234
}
```

**Example Response (Not Running):**
```json
{
  "status": "stopped",
  "health": "inactive",
  "running": false,
  "poll_count": 0,
  "settlement_count": 0,
  "last_cursor": null,
  "seen_ids_count": 0,
  "cursor_history_len": 0,
  "timestamp": 1712293453.234
}
```

### GET /api/health

The global health endpoint includes settlement poller status in `checks.settlement_poller`:

```json
{
  "status": "healthy",
  "timestamp": 1712293453,
  "degraded": false,
  "checks": {
    "settlement_poller": {
      "status": "running",
      "running": true,
      "poll_count": 142,
      "settlement_count": 7
    },
    ...
  }
}
```

### GET /startup

Shows detailed startup status including the settlement poller service:

```json
{
  "started_at": 1712290000.0,
  "services": {
    "kalshi_settlement_poller": {
      "status": "running",
      "started_at": 1712290123.456
    },
    ...
  }
}
```

## Verification Checklist

To confirm the settlement poller is working correctly in production:

### 1. Initial Startup Verification

After deploying or restarting the server, verify the poller started successfully:

```bash
# Check startup status
curl http://localhost:8000/startup | jq '.services.kalshi_settlement_poller'

# Should show:
# {
#   "status": "running",
#   "started_at": <timestamp>
# }
```

### 2. Active Polling Verification

Verify the poller is actively polling by checking if `poll_count` increases over time:

```bash
# First check
curl http://localhost:8000/health/settlement_poller | jq '.poll_count'
# Output: 10

# Wait 60-120 seconds (default poll interval is 60s)

# Second check
curl http://localhost:8000/health/settlement_poller | jq '.poll_count'
# Output: 11 or 12 (should have increased)
```

**Expected behavior:**
- `poll_count` should increase by ~1 every 60 seconds
- If `poll_count` stays at 0 or doesn't increase, the poller is not running

### 3. Settlement Processing Verification

When markets settle, verify `settlement_count` increases:

```bash
# Before market settlement
curl http://localhost:8000/health/settlement_poller | jq '.settlement_count'
# Output: 5

# After markets settle (check Kalshi for settled markets)

# After settlement
curl http://localhost:8000/health/settlement_poller | jq '.settlement_count'
# Output: 8 (increased by 3 if 3 new markets settled)
```

### 4. Cursor Persistence Verification

Verify the cursor is being saved and will survive restarts:

```bash
# Check cursor before restart
curl http://localhost:8000/health/settlement_poller | jq '.last_cursor, .cursor_history_len'
# Output: "abc123def456", 15

# Restart the server
# (settlements that occurred before the restart should NOT be reprocessed)

# Check cursor after restart
curl http://localhost:8000/health/settlement_poller | jq '.last_cursor'
# Output: "abc123def456" (same cursor - no reprocessing)
```

### 5. Watch Mode for Live Monitoring

Use the verification script in watch mode for continuous monitoring:

```bash
python scripts/verify_settlement_poller.py --watch

# Expected output:
# [10:30:00] ✓ Status: running         | Polls:  142      | Settlements:    7
# [10:30:10] ✓ Status: running         | Polls:  142      | Settlements:    7
# [10:31:00] ✓ Status: running         | Polls:  143 (+1) | Settlements:    7
```

## Troubleshooting

### Poller status is "not_configured"

**Cause:** Kalshi credentials are not configured in settings.

**Solution:**
1. Check `settings.KALSHI_API_KEY_ID` is set
2. Check `settings.KALSHI_PRIVATE_KEY_PATH` or `settings.KALSHI_PRIVATE_KEY_PEM` is set
3. Verify credentials are not set to "change_me"

### Poller status is "stopped"

**Cause:** The poller was started but then stopped, or startup failed.

**Solution:**
1. Check server logs for startup errors
2. Restart the server
3. Check `/startup` endpoint for error details

### poll_count is not increasing

**Cause:** The poll loop is stuck or crashed.

**Solution:**
1. Check server logs for exceptions in "kalshi-settlement-poller" task
2. Restart the server
3. Verify Kalshi API is accessible (`GET /portfolio/settlements`)

### settlement_count is 0 after markets settle

**Cause:** Either no markets have settled, or the settlement hooks are not firing.

**Solution:**
1. Verify markets have actually settled on Kalshi
2. Check `merid/reconciliation.py` logs for settlement hook execution
3. Verify `ct.record_trade_result()` is being called in settlement hooks

## Integration with CT Bankroll Invariant

The settlement poller is critical for the CT bankroll invariant feature:

1. **Settlement Detection:** Poller detects when Kalshi markets settle
2. **Hook Firing:** `merid/reconciliation.py` fires settlement hooks
3. **PnL Recording:** Hooks call `ct.record_trade_result(pnl_cents)`
4. **Invariant Check:** CT's `check_bankroll_invariant()` verifies realized PnL matches balance changes

**To verify the full pipeline:**

```bash
# 1. Check poller is running and has processed settlements
curl http://localhost:8000/health/settlement_poller | jq '{running, settlement_count}'

# 2. Check CT bankroll status shows total_pnl_cents increasing
curl http://localhost:8000/api/v1/ct/status | jq '.bankroll'

# Expected output:
# {
#   "total_pnl_cents": 15000,  // Should match settlement_count * avg_pnl
#   "session_start_balance_cents": 100000,
#   "last_invariant_delta_cents": -200,  // Should be small (< 500)
#   ...
# }
```

## Related Documentation

- [CT Bankroll Invariant Design](./BANKROLL_INVARIANT_DESIGN.md)
- Settlement poller implementation: `merid/event_venues/kalshi/settlement_poller.py`
- Settlement hooks: `merid/reconciliation.py` (line 540-580)
- Startup wiring: `web/main.py` (line 2163-2175)
- Shutdown wiring: `web/main.py` (line 2629-2634)
