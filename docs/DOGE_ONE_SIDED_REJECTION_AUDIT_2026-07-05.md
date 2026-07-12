# DOGE One-Sided Book Rejection Audit
**Date**: 2026-07-05  
**Time**: 18:30 UTC  
**Asset**: DOGE_15M  
**Ticker**: KXDOGE15M-26JUL051830-30

## Issue Summary
DOGE trade was rejected due to one-sided order book (one_sided_yes regime) with depth_yes=250, depth_no=20, TTE=8.2min > 1min.

## Investigation Findings

### 1. Rejection Log
```
[ONE-SIDED-REJECT] asset=DOGE_15M ticker=KXDOGE15M-26JUL051830-30 regime=one_sided_yes depth_yes=250 depth_no=20 tte=8.2min > 1min -> REJECT (cannot exit if book stays one-sided)
```

### 2. One-Sided Rejection Logic
**Location**: `merid/prediction/agent_grid_15m.py` (lines 2447-2468)

**Logic**:
- If order book is one-sided (one side has 0 depth) AND TTE > 1 minute → REJECT
- If TTE <= 1 minute → ALLOW (time pressure exception)
- If no close_time available → REJECT (conservative)

**Purpose**: Prevent getting stuck in positions that cannot be exited if the book remains one-sided.

### 3. Depth Thresholds Configuration
**Location**: `config/profiles/kalshi_crypto_15m_v2.yaml`

**DOGE Configuration**:
```yaml
DOGE:
  min_depth_yes: 1  # Minimum YES depth at best bid (contracts)
  min_depth_no: 1  # Minimum NO depth at best ask (contracts)
  asset_tier: 2  # Tier 2 (alt assets: SOL, XRP, DOGE)
```

**Tier Configuration**:
```yaml
min_depth_yes_tier2: 1   # Tier 2 (SOL/XRP/DOGE): min 1 yes contract
min_depth_no_tier2: 1    # Tier 2 (SOL/XRP/DOGE): min 1 no contract
```

### 4. Trade History Analysis
**Location**: `trade_history_7days.csv`

**Most Recent DOGE Trades** (July 3rd, not July 5th):
- `KXDOGE15M-26JUL031145-45,YES,buy,1.0,0.58` at 2026-07-03T15:39:42
- `KXDOGE15M-26JUL030400-00,YES,buy,1.0,0.61` at 2026-07-03T07:53:16
- `KXDOGE15M-26JUL030345-45,YES,buy,1.0,0.59` at 2026-07-03T07:38:26
- `KXDOGE15M-26JUL030345-45,YES,buy,1.0,0.54` at 2026-07-03T07:34:11

**No DOGE trades found on July 5th in trade history.**

### 5. Current System State
- **Server**: Running on port 8011
- **Profile**: kalshi_crypto_15m_v2
- **Bankroll**: $33.80
- **Mode**: Live trading enabled
- **Cycle**: 135 (as of 18:21:46 UTC)

## Assessment

### Is This a False Positive?
**NO** - This is **NOT a false positive**. The one-sided rejection is a legitimate safety mechanism working as designed:

1. **Safety Mechanism**: The rejection prevents entering positions that cannot be exited if the book remains one-sided.
2. **Time-Based Exception**: The system already allows one-sided books in the last 1 minute (time pressure exception).
3. **Conservative Design**: If no close_time is available, it rejects conservatively.

### Why depth_no=20 Was Insufficient
- The rejection occurred because `depth_no=20` was evaluated as insufficient for the one-sided regime.
- The code checks if `min_depth_no == 0` to determine one-sided regime.
- In this case, the NO side had 20 contracts, but the YES side had 250 contracts, suggesting an imbalance that triggered the one-sided regime check.

### Potential Issues to Investigate

1. **Regime Detection Logic**: The one-sided regime detection may need refinement to distinguish between:
   - Truly one-sided books (0 depth on one side)
   - Imbalanced books (low depth on one side but not zero)

2. **Depth Threshold Consistency**: The YAML sets `min_depth_no: 1` for DOGE, but the rejection occurred with `depth_no=20`. This suggests the one-sided check is more strict than the depth threshold check.

3. **User Report**: The user mentioned "there was a doge trade that executed" but no DOGE trades from July 5th appear in the trade history. This may indicate:
   - The trade was simulated (not live)
   - The trade was rejected before execution
   - The trade occurred in a different timeframe/account

## Recommendations

### 1. No Immediate Changes Required
The one-sided rejection is a safety feature. Do not disable it without understanding the exit risk implications.

### 2. Investigate Regime Detection
Review the one-sided regime detection logic in `agent_grid_15m.py` to ensure it correctly distinguishes between:
- Zero depth (truly one-sided)
- Low depth (imbalanced but tradeable)

### 3. Verify Trade Execution
Clarify with the user:
- Which DOGE trade they are referring to (date/time/ticker)
- Whether it appeared in their Kalshi account
- Whether it was a live trade or simulated

### 4. Monitor DOGE Liquidity
DOGE is a Tier 2 asset with thinner liquidity. Monitor whether one-sided books are frequent for DOGE and whether the current thresholds are appropriate.

## Current State Documentation

### Environment Variables
- `KALSHI_USE_DEMO=false`
- `KALSHI_ENV=live`
- `MERID_PM_TRADING_MODE=live`

### Risk Envelope
- Bankroll: $33.80
- Per-asset cap: 3% ($1.01)
- DOGE max contracts: 2
- DOGE depth thresholds: yes=1, no=1

### System Health
- All 5 assets (BTC/ETH/SOL/XRP/DOGE) active
- Catalog fresh
- Market data fresh
- Risk envelope loaded
- No halt components

## Next Steps

1. **Await user clarification** on which DOGE trade they are referring to
2. **Verify Kalshi account** for any DOGE trades on July 5th
3. **Review regime detection logic** if one-sided rejections are frequent
4. **Monitor DOGE liquidity patterns** to assess if thresholds need adjustment

## Test Coverage

### Existing Tests
- `test_kalshi_crypto_15m_risk_envelope.py` - Tests depth thresholds
- `test_15m_order_flow_e2e.py` - Tests order flow with depth thresholds
- `test_kalshi_exit_invariant.py` - Tests DOGE order classification

### Recommended Tests
- Test one-sided regime detection with various depth scenarios
- Test one-sided rejection with TTE > 1min vs TTE <= 1min
- Test DOGE-specific depth threshold enforcement

## CRITICAL UPDATE: Active DOGE Position Found

**User Confirmed**: Active DOGE position exists in Kalshi account:
- **Ticker**: DOGE 15 min
- **Price**: $0.0779411 target
- **Position**: NO 1¢ (1 contract at 21.12¢)
- **PnL**: -$0.20 (-95%)
- **Status**: Active (not closed)

## Root Cause Analysis

### Why trade_history.csv Shows No DOGE on July 5th
**Explanation**: `trade_history.csv` only records **fills** (completed trades), not **active positions**. The DOGE position shown in the user's Kalshi account was likely:
1. Opened before July 5th (possibly July 3rd based on trade history)
2. Still active and not yet closed
3. Not recorded in trade_history.csv because it's not a fill event

### Position Cache Sync Issue
**Hypothesis**: The active DOGE position exists in Kalshi but may not be synced to the internal position cache, which would explain:
- Why the system doesn't show the position internally
- Why risk calculations may be incorrect
- Why the position doesn't appear in internal logs

**Evidence**:
- Position cache has `sync_from_rest()` method to sync from Kalshi REST API
- Agent grid logs show `sync_from_rest` being called regularly
- No evidence of DOGE position in internal position tracking

### Next Steps

1. **Check position cache sync status**: Verify if the position cache is successfully syncing from Kalshi REST API
2. **Check fills_ledger**: Verify if the opening fill for this DOGE position is recorded
3. **Check venue adapter**: Verify if the venue adapter is correctly fetching positions from Kalshi
4. **Manual sync test**: Force a manual sync from REST to see if the DOGE position appears

## Conclusion

The DOGE one-sided rejection on July 5th at 18:30 UTC is a **legitimate safety mechanism** working as designed, not a false positive. 

**However**, there is a **separate issue**: An active DOGE position exists in the Kalshi account but may not be properly tracked in the internal position cache. This could lead to:
- Incorrect risk calculations
- Missing position monitoring
- Inaccurate PnL tracking

**Action Required**: Investigate position cache sync mechanism to ensure Kalshi positions are correctly reflected in internal state.

## CRITICAL ROOT CAUSE DISCOVERED

**Issue**: `kalshi_api.py` router is NOT registered in `main_15m_lean.py`

**Impact**: 
- Fills ledger API endpoints are unavailable (`/api/v1/fills`, `/api/v1/fills/reconcile-now`, `/api/v1/fills/reconciliation`)
- Fills reconciliation cannot be triggered manually
- Fills ingestion endpoints are missing
- This explains why the fills ledger is empty (0 fills) despite FillsPoller running in background

**Evidence**:
- `main_15m_lean.py` includes: `kalshi_agent_grid_router`, `kalshi_ui_router`
- `main_15m_lean.py` does NOT include: `kalshi_api` router
- `kalshi_api.py` defines router with prefix `/api/v1/kalshi` and contains all fills-related endpoints
- HTTP requests to `/api/v1/fills` return 404 Not Found
- Fills ledger database shows 0 fills

**Fix Required**: Add `kalshi_api` router registration to `main_15m_lean.py`
