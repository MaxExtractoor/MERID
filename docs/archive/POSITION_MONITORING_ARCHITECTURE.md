# Position Monitoring Architecture

**CRITICAL FIX: 2026-07-07 - Consolidation of Position Monitoring System**

## Overview

The MERID trading system previously had duplicate position monitoring logic in two separate components:
- `PositionMonitor` (`merid/position_management/position_monitor.py`)
- `KalshiPositionCache` (`merid/event_venues/kalshi/position_cache.py`)

This duplication caused several issues:
- **Race conditions**: Two separate polling loops could conflict
- **Callback bypass**: Staged exits in position_cache called `route_order_async` directly, bypassing the exit intent callback system
- **Missing agent_id**: Staged exits used "position_cache" instead of actual agent_id (e.g., BTC_15M), breaking window exposure tracking
- **No swing mode**: Staged exits didn't enable swing mode logic for opposite-side entries
- **Inconsistent error handling**: Different error handling between the two systems

## Solution: Single Authoritative Monitoring System

**PositionMonitor is now the authoritative exit system** for all position monitoring and exit logic.

### PositionMonitor Responsibilities

PositionMonitor (`merid/position_management/position_monitor.py`) now handles ALL exit conditions:

1. **Extreme Profit Exits** (99c YES / 1c NO)
   - Highest priority exit for guaranteed wins
   - Triggered when price reaches 99c for YES or 1c for NO

2. **Dynamic Take Profit** (Laddered Exits)
   - Entry price zone-based exit targets
   - Example: Entry 25-30c → Exit 50-60c, Entry 30-40c → Exit 60-70c
   - Edge quality adjustment for high/low edge positions

3. **Ratchet Profit Floor** (80-85c Range)
   - Activates when price hits 85c threshold
   - Sets profit floor at 80c
   - Trims position to 1 contract when price drops below floor
   - Mandatory exit if floor breached after hold period expires

4. **Trailing Stop Activation**
   - Activates after minimum profit threshold (12c per 2026 research)
   - Aggressive trailing in 80-85c profit zone
   - Fixed cent trailing (e.g., 5 cents) for consistency

5. **Stop Loss / Take Profit**
   - Traditional stop loss triggers
   - Traditional take profit triggers
   - Break-even trigger at 1R (capital preservation)

6. **Staged Time-Based Exits** (NEW - Consolidated from position_cache)
   - Stage 0: Close 25% at 5 minutes
   - Stage 1: Close 25% at 10 minutes
   - Stage 2: Close 50% at 13 minutes
   - Uses proper callback routing with agent_id

7. **Exit Policy Resolution**
   - Time stop
   - Edge decay
   - Risk kill switch
   - Candle reversal patterns
   - Adaptive timing

### KalshiPositionCache Responsibilities

KalshiPositionCache (`merid/event_venues/kalshi/position_cache.py`) now handles ONLY position state management:

1. **Position State Management**
   - Fill event processing
   - Position cache updates
   - PnL tracking
   - Metadata management

2. **Position Cache Operations**
   - Add/remove positions from cache
   - Query position state
   - Position reconciliation

3. **Integration with PositionMonitor**
   - Adds new positions to PositionMonitor for monitoring
   - Provides position metadata for exit conditions
   - No longer performs exit checks directly

4. **Resting Bracket Orders** (Optional)
   - GTC sell limit at TP price
   - Gated by `MERID_RESTING_BRACKETS_ENABLED` env flag
   - Default: disabled (off-by-default for safety)

## Startup Sequence

### Production Stack (main_15m_lean.py)

1. **FastAPI Lifespan Startup**
   - Initializes all services
   - **No longer calls** `position_cache.start_monitoring()` (now a no-op)

2. **Kalshi15mLoop.start()**
   - Initializes PositionMonitor via `get_position_monitor()`
   - Calls `await self._position_monitor.start()` to start polling loop
   - Registers exit intent callback with proper agent_id derivation
   - Callback routes to `_execute_exit_order()` with swing mode logic

### Exit Intent Callback Flow

```
PositionMonitor._check_position()
  → Detects exit condition
  → Calls _emit_exit_intent()
    → Calls registered callback (loop_15m.py exit_intent_callback)
      → Calls _execute_exit_order()
        → Derives agent_id from market_id (BTC_15M, ETH_15M, etc.)
        → Enables swing mode for trailing exits
        → Submits order via route_order_async
        → Records window exposure reduction
```

## Key Benefits

### 1. Single Source of Truth
- All exit logic in one place (PositionMonitor)
- No duplicate logic or conflicting rules
- Easier to maintain and debug

### 2. Proper Callback Routing
- All exits go through the exit intent callback
- Consistent error handling and logging
- Proper agent_id derivation for window tracking

### 3. Swing Mode Integration
- Trailing exits enable swing mode for opposite-side entries
- Allows YES/NO reversal to capture profits from price swings
- Was missing in old position_cache staged exits

### 4. Window Exposure Tracking
- Exit orders use actual agent_id (e.g., BTC_15M)
- Window exposure correctly reduced when positions close
- Allows re-entry after exposure is closed out

### 5. Idempotency Guards
- Each exit reason checked only once per position
- Prevents double exits or duplicate orders
- Stage execution flags prevent re-triggering

## Configuration

### Staged Exit Configuration

Staged exits are now hardcoded in PositionMonitor with the following stages:
- Stage 0: 25% at 5 minutes
- Stage 1: 25% at 10 minutes
- Stage 2: 50% at 13 minutes

This can be made configurable via profile YAML in the future if needed.

### Resting Brackets

Resting bracket orders (GTC sell at TP) are still available but:
- Gated by `MERID_RESTING_BRACKETS_ENABLED` env flag
- Default: disabled (off-by-default for safety)
- Optional feature for advanced users

## Migration Guide

### For Developers

If you were previously using position_cache monitoring:

**OLD (Deprecated):**
```python
# This is now a no-op
position_cache = get_position_cache()
position_cache.start_monitoring()
```

**NEW (Correct):**
```python
# PositionMonitor is started by Kalshi15mLoop
# No action needed - it's automatic
```

### For Testing

Tests have been updated to reflect the new architecture:
- `test_position_monitor.py` - Tests PositionMonitor functionality
- `test_staged_time_exit.py` - Tests staged exits in PositionMonitor (updated from position_cache)

## Backward Compatibility

The consolidation maintains backward compatibility:
- `position_cache.start_monitoring()` is now a no-op (logs warning)
- `position_cache.stop_monitoring()` is now a no-op (logs warning)
- All existing PositionMonitor functionality unchanged
- Exit intent callback interface unchanged

## Testing

Run the position management tests:

```bash
pytest tests/position_management/test_position_monitor.py -v
pytest tests/position_management/test_staged_time_exit.py -v
```

## Troubleshooting

### Issue: Auto-exit not working

**Check:**
1. Is PositionMonitor running? Look for `[POSITION-MONITOR] Started` logs
2. Is exit intent callback registered? Look for `[15m-LOOP] Started PositionMonitor with exit callback` logs
3. Are positions being added to PositionMonitor? Look for `[POSITION-MONITOR-INTEGRATION] Added position to monitor` logs
4. Is PositionMonitor polling? Look for `[POSITION-MONITOR] Polling X positions` logs

### Issue: Window exposure not reducing

**Check:**
1. Are exit orders using correct agent_id? Look for agent_id in exit order logs
2. Is window exposure being recorded on position close? Check order router logs
3. Is the exit intent callback being called? Check callback logs

## References

- PositionMonitor: `merid/position_management/position_monitor.py`
- Position Model: `merid/position_management/position.py`
- Exit Policy: `merid/position_management/exit_policy.py`
- Position Cache: `merid/event_venues/kalshi/position_cache.py`
- Loop 15m: `merid/loop_15m.py`
- Main Entry: `web/main_15m_lean.py`

## Changelog

### 2026-07-07
- **CRITICAL FIX**: Consolidated position monitoring to single authoritative system
- Moved staged time-based exits from position_cache to PositionMonitor
- Disabled duplicate monitoring loop in position_cache (now no-op)
- Added staged exit tracking fields to Position model
- Updated tests to reflect new architecture
- Updated documentation

### 2026-07-06
- Added idempotency guards to prevent double exits
- Added side-aware price conversion for NO positions
- Added dynamic take profit edge quality adjustment
- Added ratchet profit floor logic
