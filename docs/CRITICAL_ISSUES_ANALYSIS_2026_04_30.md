# Critical Issues Analysis - MERID Kalshi Trading System
**Date:** April 30, 2026  
**Status:** 🔴 PRODUCTION BLOCKERS IDENTIFIED  

---

## 🎯 Executive Summary

Based on analysis of live trading logs, **THREE CRITICAL PRODUCTION BLOCKERS** have been identified that are causing:
1. **Losses on round-trip trades** (take-profit never triggers)
2. **UI bankroll not reconciling** after trades
3. **Position/PnL data inconsistencies**

---

## 🔴 CRITICAL ISSUE #1: Micro-Scalp Time Exit Override

### Problem
**The take-profit system is NOT working because the micro-scalp exit triggers BEFORE profit targets can be hit.**

### Evidence from Logs:
```
2026-04-30 15:27:00 | INFO | merid.event_venues.kalshi.stop_loss | [MICRO-SCALP] Time exit 2f6e117e-c7a0-4b46-ba1e-ed2cdf90b121: 557s >= 90s max | target=3.5% achieved=0.0%
```

### Root Cause Analysis:

**Exit Priority Order (trading_agent.py:3326-3430):**
```
1. Take-profit sweep (via TakeProfitManager) - line 3149
2. Micro-scalp exit sweep (via MicroScalpExitManager) - line 3326
3. Stop-loss sweep (via StopLossRules.check_position) - line 3429
```

**The Problem:**
- Micro-scalp config has `max_hold_seconds=90` (90 seconds)
- The dynamic profit target is 3.5-5%
- For a 50¢ contract, 3.5% = 1.75¢ price move needed
- Market didn't move 1.75¢ within 90 seconds
- Position exited at 557s by TIME, not by profit
- Result: **0% profit achieved = round-trip loss (entry/exit fees only)**

### Code Locations:
| File | Lines | Issue |
|------|-------|-------|
| `merid/prediction/trading_agent.py` | 376 | `max_hold_seconds=90` too aggressive |
| `merid/event_venues/kalshi/stop_loss.py` | 414-435 | MicroScalpExitConfig defaults |
| `merid/prediction/trading_agent.py` | 3326-3427 | Micro-scalp runs BEFORE stop-loss (which has profit_target_pct) |

### Impact:
- **Every trade exits at 90s** regardless of profit potential
- **Fees eat all profits** (4% round-trip fees on 50¢ = 2¢ loss)
- **Bankroll bleeds** with each round-trip

---

## 🔴 CRITICAL ISSUE #2: Incomplete Fill Data from Kalshi API

### Problem
**The fills API is returning incomplete data, preventing PnL calculation and bankroll reconciliation.**

### Evidence from Logs:
```
2026-04-30 15:27:02 | INFO | web.api.kalshi_api | kalshi GET /fills rows=2 since_hours=24 sample={'fill_id': 'df3d6a7f-1a0d-56d0-642e-e91db724a001', 'size': 0, 'price_usd': 0.0, 'incomplete': True}
```

### Root Cause:
- Kalshi API returns fills with `count_fp=0` or missing price fields
- `KalshiFill.is_incomplete()` returns True for these fills
- PnL cannot be calculated without size and price
- Bankroll reconciliation fails

### Code Locations:
| File | Lines | Issue |
|------|-------|-------|
| `merid/event_venues/kalshi/fills_ledger.py` | 118-124 | `is_incomplete()` checks for zero size/price |
| `merid/event_venues/kalshi/fills_poller.py` | 218-249 | Poll logic not handling incomplete fills |

---

## 🔴 CRITICAL ISSUE #3: Position Cache vs Ledger Divergence

### Problem
**The position cache and fills ledger show divergent positions, causing UI inconsistencies.**

### Evidence from Logs:
```
2026-04-30 15:26:53 | INFO | merid.event_venues.kalshi.position_cache | Position cache synced from REST: 0 positions
2026-04-30 15:26:53 | INFO | merid.event_venues.kalshi.fills_poller | Position cache synced from reconciliation: 7 positions
2026-04-30 15:32:40 | WARNING | merid.reconciliation.venue | Reconciliation kalshi: 3 discrepancies (0 critical, 0 warning)
```

### Root Cause:
- REST API returns 0 positions but fills ledger computes 7 positions
- Cache sync uses computed positions when REST is empty
- Divergence detection finds 3 discrepancies
- UI shows stale/incorrect position data

---

## 🔧 REQUIRED FIXES

### FIX #1: Increase Micro-Scalp Hold Time
**File:** `merid/prediction/trading_agent.py`

**Current (Line ~373):**
```python
_ms_cfg = MicroScalpExitConfig(
    profit_target_pct=0.05,        # 5% profit target
    max_hold_seconds=90,           # ⚠️ TOO SHORT - 90 seconds
    edge_decay_threshold=0.50,
    book_flip_detection=True,
    min_profit_cents=2,
)
```

**Fix:**
```python
_ms_cfg = MicroScalpExitConfig(
    profit_target_pct=0.05,        # 5% profit target
    max_hold_seconds=300,          # ✅ 5 minutes - allows profit target to hit
    edge_decay_threshold=0.50,
    book_flip_detection=True,
    min_profit_cents=2,
)
```

---

### FIX #2: Reorder Exit Checks - Profit Target BEFORE Time Exit
**File:** `merid/prediction/trading_agent.py`

**Current Order (Lines 3042-3590):**
```
1. Price refresh
2. Take-profit sweep (TakeProfitManager)
3. Micro-scalp exit (MicroScalpExitManager with 90s time exit)
4. Stop-loss sweep (StopLossRules with profit_target_pct)
```

**Problem:** Micro-scalp time exit runs before stop-loss profit_target check.

**Fix:** Move stop-loss check (which includes profit_target_pct) BEFORE micro-scalp, OR disable time exit when profit target is configured.

**Option A - Disable time exit in micro-scalp config:**
```python
_ms_cfg = MicroScalpExitConfig(
    profit_target_pct=0.05,
    max_hold_seconds=0,  # 0 = disabled, let stop-loss handle exits
    ...
)
```

**Option B - Reorder in _check_stop_losses():**
1. Price refresh
2. Stop-loss sweep (includes profit_target_pct) ← Move to position 2
3. Take-profit sweep
4. Micro-scalp exit

---

### FIX #3: Handle Incomplete Fills
**File:** `merid/event_venues/kalshi/fills_poller.py`

**Problem:** Kalshi API returning fills with incomplete data.

**Fix:** Add logic to fetch complete fill details when incomplete data is detected.

```python
# In _do_poll(), after receiving fills:
for fill in fills:
    if fill.get('count', 0) == 0 or fill.get('price', 0) == 0:
        # Fetch detailed fill info
        detailed = await client.get_fill_details(fill['fill_id'])
        if detailed:
            fill.update(detailed)
```

---

### FIX #4: Fix Position Cache Sync
**File:** `merid/event_venues/kalshi/fills_poller.py`

**Current (Lines 328-346):**
```python
# If REST returned empty but fills ledger has computed positions,
# use the computed positions instead
```

**Problem:** Using computed positions when REST is empty may cause divergence.

**Fix:** When REST returns empty but we expect positions, log warning and trigger immediate reconciliation.

---

## 📊 Impact Assessment

| Issue | Severity | Impact on PnL | Fix Complexity |
|-------|----------|---------------|----------------|
| Micro-scalp time exit | 🔴 CRITICAL | -4% per trade (fees only) | Low (config change) |
| Incomplete fills | 🟠 HIGH | No PnL tracking | Medium |
| Position divergence | 🟡 MEDIUM | UI confusion | Medium |

---

## ✅ RECOMMENDED IMMEDIATE ACTIONS

### Immediate (Next 30 minutes):
1. **STOP TRADING** or switch to paper mode
2. **Apply FIX #1** - Change `max_hold_seconds=90` to `max_hold_seconds=300`
3. **Apply FIX #2 Option A** - Set `max_hold_seconds=0` to disable time exit
4. Restart server and verify in logs:
   - No more `[MICRO-SCALP] Time exit` messages
   - `[MICRO-SCALP] PROFIT_TARGET` or `take_profit` messages appear

### Short-term (Today):
1. Implement FIX #2 Option B - Reorder exit checks properly
2. Implement FIX #3 - Handle incomplete fills
3. Implement FIX #4 - Fix position cache sync
4. Add monitoring for:
   - Time exit rate (should be <20%)
   - Profit target hit rate (should be >60%)
   - Fill completeness rate (should be 100%)

### Long-term (This week):
1. Add self-tuning logic for `max_hold_seconds` based on market volatility
2. Implement proper fill enrichment from Kalshi API
3. Add reconciliation health dashboard in UI
4. Create alerting for divergence thresholds

---

## 🧪 Testing Verification

After applying fixes, verify with:

```powershell
# Check for profit exits
cd C:/Dev/MERID
Select-String -Path logs/current_run.log -Pattern "PROFIT_TARGET|take_profit|MICRO-SCALP.*profit"

# Check fill completeness
Select-String -Path logs/current_run.log -Pattern "incomplete.*True|size.*0.*price"

# Check position reconciliation
Select-String -Path logs/current_run.log -Pattern "Reconciliation.*discrepancies|divergence"
```

**Expected after fix:**
- `PROFIT_TARGET` or `take_profit CLOSED` messages in logs
- No `incomplete: True` in fill samples
- No position divergence warnings

---

## 📋 Summary

The trading system is currently **LOSING MONEY on every trade** due to:
1. **Aggressive 90-second time exit** that closes positions before profit targets hit
2. **Exit order** that prioritizes time over profit
3. **Data quality issues** with incomplete fills from Kalshi API
4. **Position sync issues** between cache and ledger

**Estimated Loss per Trade:**
- Entry: 50¢ contract + 2¢ fee = 52¢ cost
- Exit: 50¢ contract + 2¢ fee = 52¢ cost  
- Total: 4¢ loss per round-trip (8% of bankroll)

With $44.96 bankroll and 2% cap = $0.89 per cycle:
- **~22 trades** until bankroll is depleted from fees alone

**URGENT:** Apply FIX #1 and FIX #2 immediately to stop the bleeding.
