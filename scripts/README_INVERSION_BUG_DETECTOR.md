# Inversion Bug & Side Conflict Detector Scripts

This directory contains scripts to detect inversion bugs and side conflicts in the MERID codebase. These scripts are designed to prevent regression of known bugs that have caused real issues in production.

## Scripts

### 1. `expose_inversion_bugs_fast.py` (Recommended)

**Purpose**: Fast scanning of critical files only  
**Usage**: 
```powershell
python scripts/expose_inversion_bugs_fast.py
```

**Files Scanned**:
- `merid/event_venues/kalshi/fills_ledger.py`
- `merid/event_venues/kalshi/client.py`
- `merid/event_venues/kalshi/order_router.py`
- `merid/event_venues/kalshi/position_cache.py`
- `merid/event_venues/kalshi/ws_bridge.py`
- `merid/event_venues/kalshi/book_freshness.py`
- `merid/event_venues/kalshi/market_state.py`
- `merid/event_venues/kalshi/orderbook.py`
- `merid/loop_15m.py`
- `merid/prediction/agent_grid_15m.py`
- `merid/execution/executors/kalshi.py`
- `merid/event_venues/kalshi/spread_edge_analytics.py`
- `merid/event_venues/kalshi/binary_price_space.py`
- `merid/position_management/position.py`
- `merid/position_management/position_monitor.py`
- `merid/position_management/unified_exit_policy_engine.py`

**Exit Codes**:
- `0`: No critical findings detected
- `1`: Critical findings detected

### 2. `expose_inversion_bugs_comprehensive.py`

**Purpose**: Comprehensive scan of all Python files  
**Usage**:
```powershell
# Fast mode (same as expose_inversion_bugs_fast.py)
python scripts/expose_inversion_bugs_comprehensive.py --fast

# Full scan (all Python files)
python scripts/expose_inversion_bugs_comprehensive.py
```

**Exit Codes**:
- `0`: No critical findings detected
- `1`: Critical findings detected

## Bug Categories Detected

### CRITICAL (P0 - Losing Money)

1. **PRICE_SPACE_INVERSION**: NO-side orders without YES-space conversion (100 - price)
   - Kalshi V2 requires YES-space wire prices for all orders
   - BUY_NO@36c should be sent as price=0.64 (YES-space)

2. **SIDE_PRICE_INVERSION**: Inverted PnL/TP/SL calculations for NO positions
   - NO positions should use own-side cents for all calculations
   - TP should be above entry for both YES and NO
   - SL should be below entry for both YES and NO

3. **CANONICAL_DUALITY_VIOLATION**: NO bid/ask not following canonical duality
   - NO_bid should equal YES_ask
   - NO_ask should equal YES_bid
   - YES + NO = 1.0

4. **THESIS_SIDE_MISSING**: Position class missing thesis_side field
   - Required by exit-order path in loop_15m
   - Without it, exit orders fail closed

5. **TP_ZONE_CONFIG**: Dynamic TP zone with exit_target below entry_max
   - Will trigger immediately at breakeven
   - Should have exit_target > entry_max

6. **MISSING_IMPORT**: Using math functions without `import math`
   - Causes NameError at runtime

7. **EXIT_POLICY_POSITION_FLIP**: Exit orders that might flip position sign
   - Over-closing positions (exit count > position size)
   - Can create exposure on opposite leg

### HIGH (P1 - Significant Impact)

1. **OFI_DEPTH_ERROR**: OFI calculation using dual ladders
   - Should use single-book depths (yes_depth - no_depth)
   - Dual ladders cause OFI to be identically 0

2. **DEADLOCK_RISK**: Using Lock instead of RLock for re-entrant operations
   - Can cause deadlocks in methods that call other methods
   - BookFreshnessTracker was affected by this

3. **TYPE_COMPARISON_BUG**: Comparing objects to enums
   - Should use `.state` or `.is_tradable()` methods
   - Direct comparison always returns False

4. **WS_REST_DIVERGENCE**: Divergence checks without REST-fallback exemption
   - Veto orders in REST-fallback mode
   - Should skip when store snapshot age > 8s

5. **OUTCOME_SIDE_CONFLICT**: Using deprecated 'side' field
   - Should use outcome_side/book_side instead
   - Deprecated field can invert NO fills

6. **EXIT_POLICY_THESIS_SIDE**: Exit orders without thesis_side validation
   - Exit order execution should validate thesis_side
   - Prevents exit order bugs

7. **EXIT_POLICY_SIDE_AGNOSTIC**: TP/SL calculations without side awareness
   - Should account for position side (YES/NO)
   - Prevents inverted TP/SL for NO positions

8. **YEAR_ROLLOVER**: Ticker parsing using current year assumption
   - Fails at year boundaries
   - Should use robust year determination

### MEDIUM (P2 - Moderate Impact)

1. **UNINITIALIZED_FIELD**: Position.entry_edge_pct not populated from signal edge
   - Field defaults to 3% if not sourced
   - Should be wired from intent.edge_pct

## Integration with CI/CD

Add to your CI pipeline:

```yaml
# Example GitHub Actions
- name: Check for inversion bugs
  run: |
    python scripts/expose_inversion_bugs_fast.py
```

```powershell
# Example in local development
python scripts/expose_inversion_bugs_fast.py
if ($LASTEXITCODE -ne 0) {
    Write-Error "Critical inversion bugs detected!"
    exit 1
}
```

## Historical Context

These scripts are based on the comprehensive bug fixes documented in `AGENTS.md`. The following major bug categories have been identified and fixed:

- **Kalshi V2 price-space inversion** (2026-08-03): NO-side orders sent with NO-space prices
- **Side/price inversion sweep** (2026-08-04): NO-side fills, PnL, TP/SL inversions
- **Exit policy audit fixes** (2026-08-03): thesis_side, TP zone config, position monitoring
- **Microstructure gate fixes** (2026-08-04): Maker/taker economics, NO-side edge calculation
- **BookFreshnessTracker deadlock** (2026-08-03): RLock instead of Lock
- **Year rollover bug** (2026-08-04): Ticker parsing at year boundaries

## Maintenance

When new inversion bugs are discovered and fixed:
1. Add a detection pattern to the appropriate `_check_*` method
2. Update this README with the new category
3. Test the script against the fixed code to ensure it passes
4. Consider adding the affected file to the critical files list in the fast scanner

## False Positives

The scripts use pattern matching and may produce false positives. If you encounter a false positive:

1. Review the code context around the reported line
2. If it's a comment or documentation, the script should already skip it
3. If it's a legitimate pattern that looks like a bug but isn't, consider:
   - Adding an exception to the pattern
   - Improving the pattern to be more specific
   - Documenting why this pattern is safe in the code

## Contributing

When adding new detection patterns:
1. Follow the existing naming convention: `_check_<category>_issues`
2. Use appropriate severity levels (CRITICAL for money-losing bugs)
3. Include context checks to reduce false positives
4. Update this README with the new category
5. Test against known good and bad code examples
