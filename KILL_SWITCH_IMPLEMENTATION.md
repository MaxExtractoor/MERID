# Kill Switch & Exposure API Implementation

This document describes the implementation of the three production-critical blockers required before going live with the MERID trading system.

## Overview

Three features have been implemented to ensure safe live trading operations:

1. **Auto-cancel on kill switch** - Automatically cancels all open orders when any kill switch trigger fires
2. **Per-asset/timeframe exposure API** - Provides real-time visibility into position exposure by asset and timeframe
3. **Self-test harness** - Validates both features before going live

## 1. Kill Switch Order Cancellation

### Implementation Details

**File:** `merid/risk/kill_switches.py`

**Changes:**
- Added `_cancel_all_orders_async()` method to `RiskController` class
- Modified `_trigger_kill()` to automatically cancel orders when kill switch triggers
- Only runs in LIVE mode (checks `MERID_MODE` setting)

### How It Works

When any kill switch trigger fires:
1. Kill switch is activated (`_global_kill = True`)
2. Session event is logged
3. Telegram alert is sent
4. **[NEW]** If in LIVE mode, order cancellation task is started:
   - Connects to Kalshi client
   - Fetches all open orders via `get_open_orders()`
   - Cancels orders in batches of 20 using `batch_cancel_orders()`
   - Logs structured event with `kill_switch_cancelled_orders={count}`

### Kill Switch Triggers

All trigger types will auto-cancel orders:
- **Manual** - `emergency_stop("reason")`
- **Daily Loss** - When daily P&L loss exceeds limit
- **Position Limit** - When total position value exceeds maximum
- **Error Threshold** - When too many errors occur in 1 hour
- **Circuit Breaker** - When all venues are circuit-broken

### Example Log Output

```
[CRITICAL] [risk] KILL SWITCH: Canceling all open orders (reason: daily_loss)
[WARNING] [risk] KILL SWITCH: Found 15 open orders, canceling in batches...
[CRITICAL] [risk] KILL SWITCH: Canceled 15 orders, 0 failed (reason: daily_loss)
```

### Structured Event

```json
{
  "category": "kill_switch",
  "severity": "critical",
  "title": "Kill switch cancelled 15 orders",
  "detail": "Kill switch triggered (daily_loss), canceled 15 orders, 0 failed",
  "metadata": {
    "kill_switch_cancelled_orders": 15,
    "failed_orders": 0,
    "reason": "daily_loss"
  }
}
```

## 2. Exposure API

### Implementation Details

**File:** `web/api/exposure_api.py`

**Endpoint:** `GET /api/v1/exposure/by-asset-timeframe`

### Query Parameters

- `asset` (optional) - Filter by asset: BTC, ETH, SOL, XRP, DOGE
- `timeframe` (optional) - Filter by timeframe: 15m, 1h, 4h, 1d

### Response Schema

```json
[
  {
    "asset": "BTC",
    "timeframe": "15m",
    "net_exposure_usd": 1234.56,
    "gross_exposure_usd": 1234.56,
    "contracts_long": 10,
    "contracts_short": 0,
    "cap_used_pct": 41.15,
    "cap_max_usd": 3000.0
  },
  {
    "asset": "BTC",
    "timeframe": "1h",
    "net_exposure_usd": 2500.00,
    "gross_exposure_usd": 2500.00,
    "contracts_long": 20,
    "contracts_short": 0,
    "cap_used_pct": 83.33,
    "cap_max_usd": 3000.0
  }
]
```

### Field Definitions

- **asset** - Cryptocurrency asset (BTC, ETH, SOL, XRP, DOGE)
- **timeframe** - Market timeframe (15m, 1h, 4h, 1d)
- **net_exposure_usd** - Net directional exposure (long - short)
- **gross_exposure_usd** - Total exposure (|long| + |short|)
- **contracts_long** - Number of long contracts
- **contracts_short** - Number of short contracts
- **cap_used_pct** - Percentage of configured cap used
- **cap_max_usd** - Maximum allowed exposure for this asset/timeframe

### Usage Examples

```bash
# Get all exposures
curl http://localhost:8000/api/v1/exposure/by-asset-timeframe

# Filter by asset
curl http://localhost:8000/api/v1/exposure/by-asset-timeframe?asset=BTC

# Filter by timeframe
curl http://localhost:8000/api/v1/exposure/by-asset-timeframe?timeframe=15m

# Combined filters
curl http://localhost:8000/api/v1/exposure/by-asset-timeframe?asset=ETH&timeframe=1h
```

### How It Works

1. Fetches all open positions from Kalshi venue adapter
2. Parses Kalshi tickers to extract asset and timeframe:
   - `KXBTC-15M-26MAR25-T95000` → BTC, 15m
   - `KXETH-D1-26MAR25-T3500` → ETH, 1d
3. Aggregates positions by (asset, timeframe) tuple
4. Calculates net/gross exposure and contract counts
5. Computes cap utilization percentage
6. Returns zero exposures for configured combos if no positions

## 3. Self-Test Harness

### Implementation Details

**File:** `merid/infra/self_test.py`

**Run:** `python -m merid.infra.self_test [--verbose]`

### Tests Performed

1. **Manual Kill Switch Trigger**
   - Triggers kill switch via `emergency_stop()`
   - Verifies `can_trade()` returns False
   - Resets kill switch
   - Verifies trading resumes

2. **Daily Loss Kill Switch**
   - Records loss exceeding daily limit
   - Verifies kill switch activates automatically
   - Resets for next tests

3. **Exposure API Structure**
   - Calls `/api/v1/exposure/by-asset-timeframe`
   - Validates response is a list
   - Checks all required fields are present
   - Validates no NaN or None values

4. **Exposure API Filtering**
   - Tests asset filter (`?asset=BTC`)
   - Validates only filtered results are returned

### Exit Codes

- **0** - All tests passed, ready for live mode ✅
- **1** - One or more tests failed, DO NOT go live ❌

### Example Output

```
============================================================
MERID SELF-TEST HARNESS
============================================================

Testing Kill Switch Functionality...
✅ PASS: kill_switch_manual_trigger - Manual kill switch trigger and reset successful
✅ PASS: kill_switch_daily_loss_trigger - Daily loss kill switch trigger successful

Testing Exposure API...
✅ PASS: exposure_api_structure - Exposure API structure valid (20 entries)
✅ PASS: exposure_api_asset_filter - Asset filter working (4 BTC entries)

============================================================
SELF-TEST SUMMARY
============================================================
Total tests: 4
Passed: 4
Failed: 0

✅ ALL SELF-TESTS PASSED - READY FOR LIVE MODE
```

## Pre-Live Deployment Checklist

Before switching `MERID_MODE` to `LIVE`:

- [ ] **Run self-test harness**
  ```bash
  python -m merid.infra.self_test --verbose
  ```
  Must show: `✅ ALL SELF-TESTS PASSED - READY FOR LIVE MODE`

- [ ] **Test in simulation with real orders**
  1. Place 2-3 resting orders on Kalshi in sim mode
  2. Trigger kill switch manually via API or `emergency_stop()`
  3. Verify all orders are canceled
  4. Check kill switch status endpoint shows correct reason
  5. Verify no new orders can be placed

- [ ] **Verify exposure API**
  ```bash
  # Should return valid data with no errors
  curl http://localhost:8000/api/v1/exposure/by-asset-timeframe
  ```

- [ ] **Dashboard integration**
  - Verify exposure API data displays correctly in dashboard
  - Check cap utilization warnings work
  - Confirm heatmap visualization is accurate

- [ ] **Monitor first live kill switch trigger**
  - When first kill switch fires in live mode:
  - Verify all orders are canceled
  - Check structured events are logged
  - Confirm Telegram alert is sent
  - Validate no orders can be placed while killed

## Architecture Alignment

This implementation follows industry best practices:

### Kill Switch with Auto-Cancel
- **CME Group**: [Globex Credit Controls Kill Switch](https://www.cmegroup.com/tools-information/webhelp/globex-credit-controls/Content/Kill-Switch.html)
  - "A kill switch that blocks new orders and cancels resting ones is standard for automated trading controls"

- **Binance**: [Kill Switch FAQ](https://www.binance.com/en/support/faq/detail/17f031ed1a5642ab9c74a7b64b6864d2)
  - Auto-cancellation prevents accumulating risk when trading is halted

### Exposure Monitoring
- **FIA**: [Automated Trading Risk Controls White Paper](https://www.fia.org/sites/default/files/2024-07/FIA_WP_AUTOMATED%20TRADING%20RISK%20CONTROLS_FINAL_0.pdf)
  - Real-time exposure monitoring is a core risk control requirement

- **Datasoft**: [Exposure Monitoring](https://datasoft.global/platform/fx-dealing-platform/exposure-monitoring/)
  - Per-asset and per-timeframe exposure visibility enables proactive risk management

### Pre-Live Testing
- **Best Practices**: [Automated Trading Platform Guide](https://www.goatfundedtrader.com/blog/best-automated-trading-platform)
  - Self-test validation before live deployment is standard practice

## Technical Notes

### Mode-Aware Cancellation

Order cancellation only runs in LIVE mode to prevent:
- Unnecessary API calls in simulation/paper mode
- Rate limit pressure during testing
- Confusion in logs from sim-mode cancellations

The check is: `if settings.MERID_MODE == "LIVE"`

### Batch Cancellation

Orders are canceled in batches of 20 because:
- Kalshi API limits batch cancel to 20 orders per call
- More efficient than individual cancels
- Reduces rate limit pressure
- Faster execution under stress

### Error Handling

Kill switch activation is resilient:
- Order cancellation runs in background task (doesn't block kill)
- Exceptions are caught and logged
- Kill switch still activates even if cancellation fails
- Structured events logged for audit trail

### Exposure Cap Configuration

Default caps per asset/timeframe can be overridden via settings:
- `MERID_MAX_EXPOSURE_{ASSET}_{TIMEFRAME}` (e.g., `MERID_MAX_EXPOSURE_BTC_15M`)
- If not set, uses sensible defaults (smaller for shorter timeframes)

## Files Modified/Created

- `merid/risk/kill_switches.py` - Kill switch with auto-cancel
- `web/api/exposure_api.py` - Exposure API endpoint (new)
- `web/main.py` - Router registration
- `merid/infra/self_test.py` - Self-test harness (new)
- `merid/infra/__init__.py` - Package init (new)

## Testing Status

✅ All code passes Python syntax checks
✅ Self-test harness ready
⏭️ Awaiting validation in simulation mode
⏭️ Ready for live deployment after validation

---

**Last Updated:** 2026-03-29
**Status:** Implementation Complete, Ready for Testing
