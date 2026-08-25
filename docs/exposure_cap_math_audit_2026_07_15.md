# $1 Exposure Cap Math Audit Report (2026-07-15)

## Objective
Audit the $1 exposure cap math across 5 assets (BTC, ETH, SOL, XRP, DOGE) to ensure:
1. Top edge selection respects $1 total risk
2. All combination possibilities are calculated correctly
3. Edge/spread combinations are properly evaluated
4. No discrepancies between order router and execution

## Components Audited

### 1. GlobalAllocator (`merid/risk/profiles/global_allocator.py`)

**Purpose**: Top-N edge knapsack allocator for candidate selection under $1 cap

**Algorithm**:
```python
# Group candidates by asset (1 per asset max)
asset_candidates = {}
for candidate in price_filtered:
    if candidate.asset not in asset_candidates:
        asset_candidates[candidate.asset] = candidate  # Keep best per asset

unique_candidates = list(asset_candidates.values())

# Try all combinations (2^n where n=5, so max 32 combinations)
for r in range(1, len(unique_candidates) + 1):
    for combo in combinations(unique_candidates, r):
        total_notional = sum(c.notional_usd for c in combo)
        
        # Skip if exceeds cap
        if total_notional > self.venue_cap_usd:  # $1.00
            continue
        
        # Check per-asset concentration limit
        combo_valid = True
        for candidate in combo:
            asset_current = current_positions.get(candidate.asset, 0.0)
            asset_with_order = candidate.notional_usd
            max_asset_notional = self.venue_cap_usd * self.max_single_asset_fraction  # 1.00 * 1.00 = $1.00
            if asset_with_order > max_asset_notional:
                combo_valid = False
                break
        
        if not combo_valid:
            continue
        
        # Calculate total edge score for this combination
        total_edge = sum(c.edge_score for c in combo)
        
        # Prefer combination with higher total edge
        # If tied, prefer lower notional (cheaper)
        if total_edge > best_total_edge or (total_edge == best_total_edge and total_notional < best_total_notional):
            best_combination = list(combo)
            best_total_edge = total_edge
            best_total_notional = total_notional
```

**Configuration**:
- `venue_cap_usd = 1.00` (hard $1 cap)
- `max_single_asset_fraction = 1.00` (allows single order to use full cap)
- `min_price_cents = 10`, `max_price_cents = 75` (canonical range)
- Per-asset edge thresholds: BTC 1.75%, ETH 2.0%, SOL 2.5%, XRP 3.0%, DOGE 3.5%

**Math Verification**:
- ✅ Correctly sums notional: `total_notional = sum(c.notional_usd for c in combo)`
- ✅ Correctly checks cap: `if total_notional > self.venue_cap_usd`
- ✅ Correctly calculates edge score: `total_edge = sum(c.edge_score for c in combo)`
- ✅ Correctly prefers higher edge: `if total_edge > best_total_edge`
- ✅ Ties broken by lower notional: `or (total_edge == best_total_edge and total_notional < best_total_notional)`

**Issue Found**: Comment on line 165 said "10c-50c canonical range" but code uses 10-75c
- **Status**: FIXED - updated comment to "10c-75c canonical range"

### 2. GlobalSlotAllocator (`merid/risk/global_slot_allocator.py`)

**Purpose**: Runtime $1 exposure cap enforcement with slot-based position management

**Algorithm**:
```python
def can_allocate(self, entry_price_cents: int, asset: str) -> Tuple[bool, str]:
    # Check price range
    if entry_price_cents < self.MIN_ENTRY_CENTS:  # 10
        return False, f"Entry price {entry_price_cents}c below minimum {self.MIN_ENTRY_CENTS}c"
    
    if entry_price_cents > self.MAX_ENTRY_CENTS:  # 75
        return False, f"Entry price {entry_price_cents}c above maximum {self.MAX_ENTRY_CENTS}c"
    
    # Check available exposure
    required_exposure = entry_price_cents / 100.0
    available = self.get_available_exposure()
    
    if required_exposure > available:
        return False, (
            f"Insufficient exposure: required ${required_exposure:.2f}, "
            f"available ${available:.2f}, total ${self.get_total_exposure():.2f}"
        )
    
    return True, ""
```

**Configuration**:
- `MAX_EXPOSURE_USD = 1.00` (hard $1 cap)
- `MIN_ENTRY_CENTS = 10`, `MAX_ENTRY_CENTS = 75` (canonical range)

**Math Verification**:
- ✅ Correctly calculates required exposure: `required_exposure = entry_price_cents / 100.0`
- ✅ Correctly checks availability: `if required_exposure > available`
- ✅ Correctly validates price range: 10-75c

**Issue Found**: AllocationRequest.__post_init__ validated against 10-50c instead of 10-75c
- **Status**: FIXED - changed validation from `> 50` to `> 75`

### 3. OrderRouter Execution Path

**Purpose**: Route orders to live execution with validation gates

**Validation Gates** (in order):
1. Scope validation (caller authorization)
2. Signal validation (metadata)
3. Deep OTM policy (no lotto tickets)
4. Position lifecycle (no orphaned positions)
5. Deployment safety (deep OTM/ITM distance)
6. Market regime (basket flatness)
7. Per-trade risk limit (3% of bankroll)
8. Market state (book availability, staleness)
9. Liquidity check (depth)
10. Price validation (integer, 1-99c, 10c minimum)
11. Risk contract linkage (exit targets)
12. Pre-trade gate (dedup, fill awareness)
13. Shared risk guard (UnifiedRiskManager)
14. Trading mode resolution (VenueGate.mode)
15. Order scaling (if enabled)
16. Live routing or paper routing

**Key Math Points**:
- Per-trade risk limit: 3% of bankroll (line 2901-2934)
- Price validation: 1-99c range, 10c minimum (lines 6836-6895)
- Deep OTM policy: 10-75c canonical range (referenced in comments)

**No Math Issues Found**: OrderRouter does not perform $1 cap math - it delegates to:
- GlobalAllocator (upstream candidate selection)
- GlobalSlotAllocator (runtime slot allocation)
- UnifiedRiskManager (shared risk guard)

### 4. UnifiedRiskManager (`merid/risk/unified_risk_manager.py`)

**Purpose**: Single source of truth for all risk management

**Configuration**:
- `correlated_stack_max_usd = 1.0` (Max $1 total exposure - hard cap)
- `per_trade_max_notional_pct = 0.03` (3% per-trade limit)
- `per_trade_max_contracts = 1` (1 contract per trade)

**Math Verification**:
- ✅ Correctly enforces $1 cap via `correlated_stack_max_usd`
- ✅ Correctly enforces per-trade limits
- ✅ Bankroll-based dynamic limits

## Combination Analysis

### Example Combinations Under $1 Cap

Given 5 assets with prices in 10-75c range, here are valid combinations:

**Single Asset** (max 1 order per asset):
- 75c contract: $0.75 exposure ✅
- 50c contract: $0.50 exposure ✅
- 10c contract: $0.10 exposure ✅

**Two Assets**:
- 75c + 25c = $1.00 exposure ✅
- 50c + 50c = $1.00 exposure ✅
- 60c + 40c = $1.00 exposure ✅
- 75c + 26c = $1.01 exposure ❌ (exceeds cap)

**Three Assets**:
- 40c + 30c + 30c = $1.00 exposure ✅
- 35c + 35c + 30c = $1.00 exposure ✅
- 50c + 30c + 20c = $1.00 exposure ✅
- 40c + 40c + 30c = $1.10 exposure ❌ (exceeds cap)

**Four Assets**:
- 30c + 25c + 25c + 20c = $1.00 exposure ✅
- 35c + 25c + 20c + 20c = $1.00 exposure ✅
- 40c + 25c + 20c + 15c = $1.00 exposure ✅

**Five Assets**:
- 25c + 20c + 20c + 20c + 15c = $1.00 exposure ✅
- 30c + 20c + 20c + 15c + 15c = $1.00 exposure ✅

### Edge Selection Algorithm

The GlobalAllocator uses the following scoring:
```python
edge_score = edge_pct * confidence
total_edge = sum(c.edge_score for c in combo)
```

**Example**:
- Asset A: edge=3.0%, confidence=0.60 → edge_score=1.8
- Asset B: edge=2.5%, confidence=0.70 → edge_score=1.75
- Asset C: edge=2.0%, confidence=0.80 → edge_score=1.6

Best combination under $1 cap would prioritize Asset A first, then B, then C.

## Findings Summary

### Issues Fixed
1. **GlobalAllocator comment**: Changed "10c-50c canonical range" to "10c-75c canonical range"
2. **AllocationRequest validation**: Changed price validation from 10-50c to 10-75c

### No Issues Found
1. **$1 cap math**: Correctly implemented in GlobalAllocator, GlobalSlotAllocator, and UnifiedRiskManager
2. **Combination evaluation**: Brute-force enumeration of all 2^5 = 32 combinations is correct
3. **Edge selection**: Total edge maximization under cap is mathematically sound
4. **Tie-breaking**: Lower notional preference is correct for risk management
5. **Per-asset limits**: `max_single_asset_fraction = 1.00` allows full cap utilization
6. **Price range**: 10-75c is consistently enforced across all components

### OrderRouter Execution Path
- No $1 cap math in OrderRouter (correct delegation)
- Multiple validation gates but no blocking issues related to $1 cap
- Orders flow correctly from GlobalAllocator → GlobalSlotAllocator → UnifiedRiskManager → OrderRouter → Execution

## Recommendations

### No Changes Required
The $1 exposure cap math is correctly implemented across all components. The system:
1. Correctly evaluates all 32 combinations of 5 assets
2. Selects the combination with highest total edge under $1 cap
3. Enforces the cap at runtime via GlobalSlotAllocator
4. Validates price range consistently (10-75c)

### Monitoring Suggestions
1. Log the chosen combination and total notional for visibility
2. Track how often the system is at full $1 capacity
3. Monitor edge distribution across assets to ensure diversification
4. Alert if no combinations fit under $1 cap (all prices too high)

## Conclusion
The $1 exposure cap math is correctly implemented. The system properly evaluates all combination possibilities, selects the best edge/spread combinations under the cap, and enforces the limit at runtime. No discrepancies found between order router and execution regarding the $1 cap.
