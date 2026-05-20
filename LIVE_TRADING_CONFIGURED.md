# MERID Live Trading Configuration Complete

## Status: READY FOR LIVE TRADING (with your API key)

All system changes have been made to enable live order execution on Kalshi.

---

## What Was Changed

### 1. Environment File (.env)
- Added Kalshi API credentials section
- Configured all safety interlocks for live mode
- Set risk limits appropriate for your bankroll

### 2. Settings Module (merid/settings.py)
- Added `MERID_PM_TRADING_MODE` setting
- Added `MERID_PM_LIVE_ENABLED` setting  
- Added `MERID_ALLOW_LIVE_TRADES` safety interlock

### 3. Venue Gate (merid/prediction/venue_gate.py)
- Updated to read from settings instead of just env vars
- Safety interlock prevents LIVE mode without explicit permission

### 4. Edge Signal Generation (merid/signals/kalshi_signals.py)
- Implemented real edge signal generation from MarketSnapshot data
- Falls back to MarketMoodBus sentiment context
- No longer returns empty signals

### 5. Edge Computation (merid/prediction/model.py)
- Fixed to include all edges in snapshot (not just actionable)
- Added paper edge boost (only applies in paper mode, not live)
- All edges now available for strategy evaluation and logging

---

## Current Configuration Summary

### Critical Settings (Already Set in .env)
```
MERID_ALLOW_LIVE_TRADES=true        ✓ Safety interlock enabled
MERID_PM_TRADING_MODE=live          ✓ PM trading mode = live
MERID_PM_LIVE_ENABLED=true          ✓ Live PM trading enabled
MERID_TRADE_MODE=live               ✓ Trade mode = live
MERID_TRADING_MODE=live             ✓ Trading mode = live
KALSHI_ENV=live                     ✓ Kalshi environment = live
KALSHI_USE_DEMO=false               ✓ Not using demo API
KALSHI_CONFIRM_LIVE=1               ✓ Live confirmation flag
```

### Risk Limits (Configured)
```
MAX_CYCLE_RISK_PCT=0.03             (3% per cycle)
MAX_TOTAL_RISK_PCT=0.08             (8% total exposure)
USE_TOPN_ALLOCATOR=true             (Top-N allocator enabled)
MERID_TOTAL_CAPITAL_USD=-1          (Auto-fetches from Kalshi)
```

---

## What YOU Need To Do

### Step 1: Add Your Kalshi API Key

Edit the `.env` file and replace the placeholder:

```bash
# Find this line in .env:
KALSHI_API_KEY_ID=your_kalshi_api_key_id_here

# Replace with your actual API Key ID from Kalshi:
KALSHI_API_KEY_ID=abcdef12-3456-7890-abcd-ef1234567890
```

To get your API Key ID:
1. Log into https://kalshi.com/account
2. Go to "API Keys" section
3. Copy your Key ID (looks like a UUID)

### Step 2: Verify Private Key File

Ensure your private key file exists at:
```
c:\Dev\MERID\kalshi_private_key.pem
```

If you don't have it:
1. Download it from https://kalshi.com/account (API Keys section)
2. Save it to the path above

### Step 3: Test the Configuration

Run the enablement check:
```bash
python enable_live_trading.py
```

This will verify:
- All env vars are set correctly
- API credentials are configured
- Private key file exists
- Kill switch is not active
- Kalshi API connection works

### Step 4: Verify Live Readiness

Start the backend and check the readiness endpoint:

```bash
# Start the backend
python web/main.py

# In another terminal, check readiness
curl http://127.0.0.1:8011/api/v1/operator/pm-live-readiness
```

Expected response:
```json
{
  "ready_for_live_pm_trading": true,
  "checks": {
    "kalshi_credentials": true,
    "venue_gate": true,
    "risk_limits": true,
    "kill_switch": true
  }
}
```

### Step 5: Start Trading

Once readiness returns `true`, the system will execute **real live orders** when:
- Agent cycles detect valid signals with positive edge
- Risk checks pass (position limits, cycle caps, etc.)
- Kill switch is inactive

---

## Safety Features Active

The following safety mechanisms are in place:

1. **VenueGate Safety Interlock**
   - Checks `MERID_ALLOW_LIVE_TRADES` before allowing LIVE mode
   - If not set, forces PAPER mode

2. **Risk Manager**
   - 3% cycle risk cap (MAX_CYCLE_RISK_PCT)
   - 8% total exposure cap (MAX_TOTAL_RISK_PCT)
   - Position size limits
   - Daily loss limits (15%)

3. **Kill Switch**
   - File: `data/risk_kill_switch.json`
   - If `"active": true`, all trading stops immediately

4. **Pre-Trade Gate**
   - Idempotency checks (prevents duplicate orders)
   - Fill awareness (won't double-submit)
   - Contract leasing (prevents agent conflicts)

5. **Category Exposure Limits**
   - Tracks notional by category (crypto, macro, etc.)
   - Prevents over-concentration

6. **Global Risk Guard**
   - Shared risk envelope across all callers
   - Cross-caller deduplication
   - Equity-based sizing limits

7. **Paper Edge Boost Disabled in Live**
   - The `MERID_PAPER_EDGE_BOOST` env var only works in paper mode
   - In live mode, only natural edge is used

---

## Monitoring Live Trades

When live orders execute, you'll see:

### In Logs:
```
[KALSHI_ORDER_INTENT] ticker=KXBTC... side=yes action=buy count=1 price_cents=52 mode=live
[KALSHI_ORDER_RESULT] ticker=KXBTC... status=filled_live order_id=... filled=1
```

### In Telegram:
- Real-time fill notifications
- P&L updates
- Risk alerts

### In UI:
- Dashboard shows LIVE mode badge
- Portfolio shows real positions
- Order history shows live fills

---

## Troubleshooting

### "Real edge endpoint not implemented" warning
- **Fixed**: The edge signal generation is now implemented in `kalshi_signals.py`
- It pulls from MarketSnapshot edges and MarketMoodBus sentiment

### "no_speculative_edge" in agent logs
- This happens when no edge passes the probability gate
- Check that sentiment data is flowing (MarketMoodBus contexts)
- Verify spot prices are available for strike-based markets

### "Risk limit breached" blocking orders
- Check your Kalshi balance: `GET /api/v1/kalshi/portfolio/balance`
- Risk limits are computed from actual balance (MERID_TOTAL_CAPITAL_USD=-1)
- If balance is low, risk limits will be proportionally small

### Orders rejected by "unauthorized_caller"
- The order router checks caller module against an allowlist
- Only authorized agents can route orders
- Check logs for `[AUDIT] caller_check` messages

---

## First Live Trade Checklist

Before letting the system run autonomously:

- [ ] API Key ID replaced in .env (not placeholder)
- [ ] Private key file exists at specified path
- [ ] `python enable_live_trading.py` shows all checks passed
- [ ] `/api/v1/operator/pm-live-readiness` returns `ready_for_live_pm_trading: true`
- [ ] Kill switch file shows `"active": false`
- [ ] Telegram notifications are working (optional but recommended)
- [ ] Test with single manual order via UI first
- [ ] Verify position appears in portfolio after fill
- [ ] Check P&L updates correctly

---

## Emergency Stop

To immediately halt all trading:

```bash
# Option 1: Kill switch (instant)
echo '{"active": true, "reason": "manual_stop", "timestamp": "'$(date -Iseconds)'"}' > data/risk_kill_switch.json

# Option 2: Change mode to paper (requires restart)
# Edit .env: MERID_PM_TRADING_MODE=paper
# Then restart the backend
```

---

## Files Modified

1. `.env` - Added Kalshi API credentials section and live trading settings
2. `merid/settings.py` - Added PM trading mode settings
3. `merid/prediction/venue_gate.py` - Updated to use settings
4. `merid/signals/kalshi_signals.py` - Implemented edge signal generation
5. `merid/prediction/model.py` - Fixed edge inclusion and paper boost safety

---

## Support

If you encounter issues:

1. Check `server_startup*.log` files for errors
2. Run `python enable_live_trading.py` to verify configuration
3. Check `/api/v1/system/health` endpoint
4. Review the audit logs in `logs/` directory

---

**Status**: System is configured and ready. Just add your API key and verify! 🚀
