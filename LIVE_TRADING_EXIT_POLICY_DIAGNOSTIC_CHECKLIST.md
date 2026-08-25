# Live Trading Exit Policy Diagnostic Checklist

## Purpose
This checklist helps verify that the exit policy is working correctly during live trading for both YES and NO positions.

## Pre-Trade Verification

### 1. Check Startup Logs
**What to look for:**
```
[15M-LOOP] Initialized PositionMonitor for TP/SL/trailing exits
[15M-LOOP] Exit intent callback verified registered: exit_intent_callback
[15m-LOOP] Started PositionMonitor with exit callback
[POSITION-MONITOR] Started (poll_interval=5s)
```

**If missing:** PositionMonitor did not start - exit policies will not execute.

### 2. Verify Profile Configuration
**Check these values in logs or profile:**
- `trailing_stop_enabled: true`
- `ratchet_profit_floor_enabled: true`
- `dynamic_take_profit.enabled: true`
- `staged_time_exit.enabled: true`

**If disabled:** Exit features are turned off in configuration.

## During Trading Verification

### 3. Check Position Addition
**What to look for when a position is opened:**
```
[POSITION-MONITOR-INTEGRATION] Added position to monitor: market=KXBTC15M-... side=yes size=1 TP=80c SL=40c trail=5R
```

**If missing:** Position was not added to monitor - will never exit.

### 4. Check Position Monitoring
**What to look for every 5 seconds:**
```
[POSITION-MONITOR] Polling N positions
[POSITION-MONITOR] Checking position=... market=... side=... entry=50c current=55c pnl=5c R=0.25 tp=80c sl=40c trailing=False
```

**If missing:** PositionMonitor is not polling - exit conditions won't be checked.

### 5. Check 99c Exit Trigger
**What to look for when price reaches 99c:**
```
[POSITION-MONITOR] EXTREME-PROFIT triggered: position=... price=99c (99c YES / 1c NO) - locking guaranteed win
[EXIT-INTENT] position=... market=... side=... reason=extreme_profit priority=90 source=position_level exit_price=99c ...
[POSITION-MONITOR-CALLBACK] Exit intent: position=... reason=extreme_profit price=99c contracts=all
[EXIT-ORDER] Routing exit order: ticker=... side=... action=sell count=1 price=99c reason=extreme_profit
```

**If missing:** 99c exit is not triggering - check side-space semantics.

### 6. Check Trailing Stop Activation
**What to look for when profit >= 12c:**
```
[POSITION-MONITOR] TRAILING profit threshold reached: position=... price=62c profit=12c - waiting 30s delay before activation
[POSITION-MONITOR] TRAILING activated (normal 5c mode): position=... price=62c profit=12c R=0.60 threshold=12c (delay elapsed)
```

**What to look for when price >= 80c:**
```
[POSITION-MONITOR] TRAILING switched to AGGRESSIVE 2c mode: position=... side=... price=82c - entered 80-85c profit zone
```

**If missing:** Trailing stop is not activating - check profit threshold and delay.

### 7. Check Trailing Stop Trigger
**What to look for when price drops to trail level:**
```
[POSITION-MONITOR] TRAIL triggered: position=... price=80c trail=80c max_fav=82c R=0.60
[EXIT-INTENT] position=... reason=trail priority=25 ...
```

**If missing:** Trailing stop is not triggering - check trail level calculation.

### 8. Check Ratchet Activation
**What to look for when price >= 85c:**
```
[POSITION-MONITOR] RATCHET activated: position=... side=... price=85c threshold=85c floor=80c
```

**What to look for when price >= 80c with size > 1:**
```
[POSITION-MONITOR] RATCHET-TRIM triggered: position=... side=... price=81c size=2 -> trim to 1 contracts (close 1)
```

**If missing:** Ratchet is not activating - check configuration.

### 9. Check Ratchet Floor Breach
**What to look for when price drops to 80c after activation:**
```
[POSITION-MONITOR] RATCHET-FLOOR-BREACH triggered: position=... side=... price=79c floor=80c - mandatory exit (hold_period=expired)
```

**If missing:** Ratchet floor is not triggering - check hold period and force_exit setting.

## Post-Exit Verification

### 10. Check Exit Order Execution
**What to look for:**
```
[EXIT-ORDER] Exit order executed successfully: order_id=... status=ACCEPTED
```

**If missing:** Exit order failed - check order router rejection reason.

### 11. Check Position Removal
**What to look for:**
```
[POSITION-MONITOR] Removed position: ... (exit_reason=extreme_profit, exit_price=99c)
```

**If missing:** Position was not removed from monitor - may cause duplicate exits.

## Side-Space Verification

### 12. YES Position at 99c
**Expected behavior:**
- YES price >= 99c triggers EXTREME_PROFIT
- Own-side price (YES cents) is used for check
- Exit order is SELL_YES

### 13. NO Position at 99c
**Expected behavior:**
- NO price >= 99c triggers EXTREME_PROFIT
- Own-side price (NO cents) is used for check
- Exit order is SELL_NO
- **CRITICAL:** NO at 99c-NO is equivalent to YES at 1c-YES (guaranteed NO win)

### 14. Trailing Stop for YES
**Expected behavior:**
- Trail level calculated from max favorable YES price
- Trigger when YES price <= trail level
- Exit order is SELL_YES

### 15. Trailing Stop for NO
**Expected behavior:**
- Trail level calculated from max favorable NO price
- Trigger when NO price <= trail level
- Exit order is SELL_NO
- **CRITICAL:** Both sides use own-side price (no 100-x mirror for NO)

## Common Issues and Fixes

### Issue: "Exit intent callback not registered"
**Cause:** PositionMonitor.start() was not called during startup.
**Fix:** Check that main_15m_lean.py calls Kalshi15mLoop.start() which starts PositionMonitor.

### Issue: "Position not added to monitor"
**Cause:** PositionCache.apply_fill() did not call monitor.add_position().
**Fix:** Check position_cache.py lines 857 and 1467 for monitor.add_position() calls.

### Issue: "99c exit not triggering for NO"
**Cause:** Side-space bug - checking YES price instead of NO price.
**Fix:** Verify position.py:should_trigger_extreme_profit() uses own-side price for both sides.

### Issue: "Trailing stop not activating"
**Cause:** Profit threshold not reached or activation delay not elapsed.
**Fix:** Check trailing_stop_min_profit_cents (default 12c) and trailing_stop_activation_delay_sec (default 30s).

### Issue: "Ratchet floor not triggering"
**Cause:** Hold period not expired or force_exit disabled.
**Fix:** Check ratchet_min_hold_after_activation_sec (default 30s) and ratchet_force_exit_on_floor_breach (default true).

### Issue: "Exit order rejected by router"
**Cause:** Missing exit_policy_id or source not whitelisted.
**Fix:** Verify exit order has exit_policy_id and source="position_monitor_exit".

## Diagnostic Script

Run the diagnostic script to verify core exit logic:
```bash
py test_exit_policy_wiring.py
```

Expected output:
- ✅ PASS: PositionMonitor Singleton
- ❌ FAIL: Callback Registration (requires startup) - EXPECTED
- ✅ PASS: Position Addition
- ✅ PASS: 99c Exit Logic
- ✅ PASS: Trailing Stop Logic
- ✅ PASS: Ratchet Floor Logic
- ✅ PASS: Profile Configuration
- ✅ PASS: Exit Priority

## Live Log Monitoring

Monitor these log patterns during live trading:
- `[POSITION-MONITOR]` - Position monitoring activity
- `[EXIT-INTENT]` - Exit intent emission
- `[POSITION-MONITOR-CALLBACK]` - Callback execution
- `[EXIT-ORDER]` - Exit order routing
- `[POSITION-MONITOR-INTEGRATION]` - Position addition

## Summary

The exit policy logic is **correctly implemented** for both YES and NO sides:
- 99c exit works for both YES (99c-YES) and NO (99c-NO)
- Trailing stop works for both sides with own-side price semantics
- Ratchet profit floor works for both sides
- All exit priorities are correctly ordered

The critical requirement is that **PositionMonitor.start() is called during startup**, which happens in:
```
main_15m_lean.py → Kalshi15mLoop.start() → PositionMonitor.start()
```

If you're experiencing exit policy failures in live trading, use this checklist to identify which step in the chain is breaking.
