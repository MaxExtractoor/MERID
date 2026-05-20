# Crypto15M Migration Checklist (2026-05-15)

## Migration Summary

**Critical Change**: Migrated from duplicate BTC lane implementations to single canonical Crypto15MLane for all 15m crypto assets.

**Before**:
- Btc15mAgent used Crypto15MLane (canonical)
- Kalshi API used BTC15MLane (legacy)
- Startup code used BTC15MLane via LaneOrchestrator (legacy)

**After**:
- All BTC 15m operations now use Crypto15MLane via registry.get_lane("BTC_15M")
- Single canonical lane implementation for all assets (BTC/ETH/SOL/XRP/DOGE)
- Eliminated split-brain behavior between two lane implementations

## Files Modified

### 1. web/api/kalshi_api.py
- **Line 6795**: Changed from `from merid.lanes.btc15m_lane import _btc15m_lane` to registry-based lookup
- **Line 7280**: Changed from `from merid.lanes.btc15m_lane import get_btc15m_lane` to registry-based lookup
- **Lines 7370-7399**: Changed lane control actions (start/stop) to use Crypto15MLane via registry
- **Line 7415**: Changed set_paper action to use Crypto15MLane via registry

### 2. web/startup_agents.py
- **Lines 171-199**: Changed from LaneOrchestrator/BTC15MLane to direct Crypto15MLane startup via registry

### 3. merid/startup_naming_validation.py (NEW)
- Created naming validation module with startup logging table
- Added WARN-only assertions for naming consistency
- Added legacy lane usage detection

### 4. merid/startup_validations.py
- **Lines 1340-1351**: Integrated naming validation into startup validation flow

### 5. merid/lanes/btc15m_lane.py
- Updated docstring to reflect deprecation and migration status

## Quick Checklist Before Next Run

### Code Verification

- [x] **Btc15mAgent** uses Crypto15MLane via `registry.get_lane("BTC_15M")`
- [x] **Kalshi API** uses Crypto15MLane via registry (all 4 locations migrated)
- [x] **Startup code** uses Crypto15MLane via registry (LaneOrchestrator removed)
- [x] **Lane/agent names** follow convention: `<ASSET>_15M` and `<Asset>15mAgent`

### Startup Log Verification

When you run `MERID_PROFILE=kalshi_crypto_15m_v2`, check for:

```
[AGENT-REGISTRY-SUMMARY] with exactly 5 asset agents:
  - Btc15mAgent (prod_15m_core)
  - Eth15mAgent (prod_15m_core)
  - Sol15mAgent (prod_15m_core)
  - Xrp15mAgent (prod_15m_core)
  - Doge15mAgent (prod_15m_core)
```

```
[Lane Registry Status]:
  - BTC_15M (Crypto15MLane, symbol=BTC, paper=False)
  - ETH_15M (Crypto15MLane, symbol=ETH, paper=False)
  - SOL_15M (Crypto15MLane, symbol=SOL, paper=False)
  - XRP_15M (Crypto15MLane, symbol=XRP, paper=False)
  - DOGE_15M (Crypto15MLane, symbol=DOGE, paper=False)
```

```
[NAMING-OK] messages for all assets
[LEGACY-LANE-OK] BTC15MLane not imported in current modules
```

### Main Loop Log Verification

During operation, check for:

```
[MAIN-LOOP] entering step with agent metadata
[REFLECTION-TRACE] with timing data
```

**Should NOT see**:
```
[BTC-LANE-MISSING-METHOD] warnings (should be fixed now)
[BTC15MLane-TRACE] logs (if seen, legacy lane still in use)
```

### Expected Behavior

1. **No split-brain**: All BTC 15m operations use the same lane implementation
2. **Consistent interface**: All 5 assets use Crypto15MLane with same methods
3. **No blocking calls**: Crypto15MLane has non-blocking I/O patterns
4. **No legacy paths**: BTC15MLane should not be imported in kalshi_crypto_15m_v2 profile

### Rollback Plan (if needed)

If issues arise, rollback steps:

1. Revert web/api/kalshi_api.py to use BTC15MLane imports
2. Revert web/startup_agents.py to use LaneOrchestrator
3. Comment out naming validation in startup_validations.py

## Naming Convention Enforcement

### Asset Codes
- BTC, ETH, SOL, XRP, DOGE (uppercase)

### Timeframe
- 15M (uppercase with M)

### Lane IDs
- `<ASSET>_15M` (e.g., BTC_15M, ETH_15M, SOL_15M, XRP_15M, DOGE_15M)

### Agent Class Names
- `<Asset>15mAgent` (e.g., Btc15mAgent, Eth15mAgent, Sol15mAgent, Xrp15mAgent, Doge15mAgent)

### Config Keys / Grid Names
- `<ASSET>_15M_AGENT` (e.g., BTC_15M_AGENT, ETH_15M_AGENT)

## Next Steps

1. **Run the system** with `MERID_PROFILE=kalshi_crypto_15m_v2`
2. **Check startup logs** for naming validation output
3. **Monitor main loop** for any [BTC15MLane-TRACE] logs (indicates legacy usage)
4. **Verify no hangs** - the migration should eliminate the split-brain issue
5. **Normalize remaining assets** - ensure ETH/SOL/XRP/DOGE use same lane interface as BTC

## Success Criteria

- ✅ All BTC 15m operations use Crypto15MLane
- ✅ No [BTC15MLane-TRACE] logs in production
- ✅ Naming validation passes with all [NAMING-OK] messages
- ✅ Main loop hangs eliminated (if caused by duplicate lanes)
- ✅ All 5 assets use consistent lane interface
