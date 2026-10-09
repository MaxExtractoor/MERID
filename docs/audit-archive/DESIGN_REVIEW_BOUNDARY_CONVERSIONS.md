# Design Review: Boundary Unit Conversions

## Executive Summary

**Date**: 2026-08-01  
**Purpose**: Verify that unit conversions at module boundaries are explicit, validated, and consistent.  
**Finding**: ⚠️ **Two different conversion patterns detected** - potential boundary leakage risk.

## Conversion Patterns Found

### Pattern A: Simple 100x Conversion (Assumes $1 Contract)
**Location**: `spread_edge_analytics.py` line 663
```python
min_executable_edge_cents = min_executable_edge_frac * 100.0
```
- **Assumes**: Contract price is always $1 (100 cents)
- **Formula**: `edge_cents = edge_pct * 100.0`
- **Risk**: Incorrect if contract price ≠ $1

### Pattern B: Contract-Price-Aware Conversion
**Location**: `order_router.py` line 383
```python
edge_cents = edge_pct * contract_price_cents
```
- **General**: Works for any contract price
- **Formula**: `edge_cents = edge_pct * contract_price_cents`
- **Correct**: For $1 contract (100c), equivalent to Pattern A
- **Risk**: None - this is the general formula

### Pattern C: Percentage Conversion (Used in agent_grid_15m.py)
**Location**: `agent_grid_15m.py` lines 5844-5846
```python
spread_pct = (spread_cents / edge_calculation_price_cents) * 100.0
taker_fee_pct = (taker_fee_cents / edge_calculation_price_cents) * 100.0
maker_fee_pct = (maker_fee_cents / edge_calculation_price_cents) * 100.0
```
- **General**: Converts cents to percentage of contract value
- **Formula**: `value_pct = (value_cents / price_cents) * 100.0`
- **Correct**: Works for any contract price
- **Risk**: None - this is the general formula

## Boundary Analysis

### Boundary 1: agent_grid_15m.py → order_router.py
**Data flow**: `edge_pct` (fraction) → `edge_cents` (cents)
**Conversion**: Pattern B (contract-price-aware)
**Status**: ✅ **CORRECT** - uses general formula

### Boundary 2: agent_grid_15m.py → spread_edge_analytics.py
**Data flow**: `min_executable_edge_frac` (fraction) → `min_executable_edge_cents` (cents)
**Conversion**: Pattern A (assumes $1 contract)
**Status**: ⚠️ **POTENTIAL ISSUE** - assumes $1 contract

### Boundary 3: spread_edge_analytics.py → order_router.py
**Data flow**: `edge_cents` (cents) → `edge_cents` (cents)
**Conversion**: None (same unit)
**Status**: ✅ **CORRECT** - no conversion needed

## Key Insight

**Kalshi contracts are always $1** (100 cents) for binary prediction markets. Therefore:
- Pattern A (`* 100.0`) is **correct** for Kalshi
- Pattern B (`* contract_price_cents`) is **also correct** for Kalshi (since contract_price_cents = 100)
- Both patterns are equivalent for Kalshi markets

**However**, the inconsistency in conversion formulas is a **maintenance risk**:
- If the system ever supports non-$1 contracts, Pattern A will break
- Pattern B is the more general and safer formula
- Having two different patterns creates confusion

## Recommendations

### Option 1: Standardize on Pattern B (Recommended)
Replace Pattern A with Pattern B everywhere:
```python
# Before (Pattern A)
min_executable_edge_cents = min_executable_edge_frac * 100.0

# After (Pattern B)
min_executable_edge_cents = min_executable_edge_frac * contract_price_cents
```
**Pros**:
- General formula works for any contract price
- Consistent with order_router.py
- Future-proof if non-$1 contracts are added

**Cons**:
- Requires passing contract_price_cents to spread_edge_analytics functions
- More verbose

### Option 2: Document Pattern A as Kalshi-Specific
Add explicit documentation that Pattern A assumes $1 contracts:
```python
# Convert fraction to cents (Kalshi contracts are always $1 = 100c)
min_executable_edge_cents = min_executable_edge_frac * 100.0
```
**Pros**:
- Minimal code change
- Makes assumption explicit

**Cons**:
- Still two different patterns
- Maintenance burden

### Option 3: Add Conversion Helper
Create a centralized conversion helper that documents the assumption:
```python
def convert_edge_fraction_to_cents_kalshi(edge_frac: float) -> float:
    """
    Convert edge fraction to cents for Kalshi markets.
    
    Kalshi binary contracts are always $1 (100 cents), so the conversion
    is simply edge_frac * 100.0. This is a Kalshi-specific conversion.
    
    For general contract prices, use convert_edge_fraction_to_cents_general().
    """
    return edge_frac * 100.0
```
**Pros**:
- Makes assumption explicit in function name
- Centralized location for conversion logic
- Easy to add general version later

**Cons**:
- Adds another helper function
- Still two different patterns (but documented)

## Verdict

**Current design is functionally correct** for Kalshi markets (all $1 contracts), but has **maintenance risk** due to inconsistent conversion patterns.

**Recommended action**: Option 3 (Add Conversion Helper) - this makes the assumption explicit while minimizing code changes. This is the safest approach that improves documentation without requiring extensive refactoring.

## Boundary Enforcement Status

| Boundary | Conversion | Validation | Tests | Status |
|----------|-----------|------------|-------|--------|
| agent_grid_15m → order_router | Pattern B (general) | ✅ Runtime validation | ✅ Cross-path tests | ✅ ENFORCED |
| agent_grid_15m → spread_edge_analytics | Pattern A (Kalshi-specific) | ❌ No validation | ❌ No tests | ⚠️ NOT ENFORCED |
| spread_edge_analytics → order_router | None (same unit) | N/A | ✅ Cross-path tests | ✅ ENFORCED |

## Next Steps

1. Add conversion helper for Pattern A with explicit documentation
2. Add runtime validation to ensure contract_price_cents = 100 when Pattern A is used
3. Add test to verify Pattern A is only used for $1 contracts
4. Document boundary conversions in UNIT_CONSISTENCY_AUDIT.md
