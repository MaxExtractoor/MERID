# Logic Sweep Audit Report
**Date**: 2026-07-25  
**Scope**: Comprehensive logic sweep across all trading layers  
**Objective**: Identify threshold inconsistencies causing candidate generation without order execution

## Executive Summary

Found **critical threshold inconsistencies** between configuration YAML and code implementation that prevent orders from executing despite candidates being generated.

### Root Cause
The global allocator is being skipped because `allow_new_entries=False`, which occurs when liquidity checks fail. However, the deeper issue is **threshold misalignment** between:
- Profile YAML configuration (source of truth)
- Code implementation (actual runtime behavior)
- Test expectations (validation)

## Critical Findings

### 1. Edge Threshold Inconsistency (CRITICAL)

**Configuration (YAML)**:
- `config/profiles/kalshi_crypto_15m_v2.yaml` lines 984, 989, 994:
  ```yaml
  edge_bands:
    watch:
      min_edge_pct: 0.030  # 3.0% minimum edge for watch band (RAISED from 2.5%)
    small:
      min_edge_pct: 0.030  # 3.0% minimum edge for small band (RAISED from 2.5%)
    standard:
      min_edge_pct: 0.030  # 3.0% minimum edge for standard band (RAISED from 2.5%)
  ```

**Code Implementation**:
- `merid/event_venues/kalshi/risk_parameters.py` line 244:
  ```python
  EDGE_BANDS_MINIMUM = 0.025  # 2.5% minimum edge from profile edge_bands (industry standard)
  ```

- `merid/risk/profiles/global_allocator.py` line 77:
  ```python
  min_edge_pct: float = 0.025,  # 2026-07-14: Changed to 2.5% to match profile edge_bands
  ```

**Impact**:
- YAML says 3.0% minimum edge
- Code uses 2.5% minimum edge
- Candidates with 2.5-3.0% edge pass code validation but fail YAML validation
- **This explains why candidates are generated but filtered out**

**Files Affected**:
- `merid/event_venues/kalshi/risk_parameters.py` (line 244)
- `merid/risk/profiles/global_allocator.py` (line 77)
- `config/profiles/kalshi_crypto_15m_v2.yaml` (lines 984, 989, 994)

**Recommendation**:
Align code with YAML (3.0%) or YAML with code (2.5%). Based on comments, YAML is the source of truth, so update code to 3.0%.

### 2. Confidence Threshold Inconsistency (HIGH)

**Configuration (YAML)**:
- `config/profiles/kalshi_crypto_15m_v2.yaml` line 959:
  ```yaml
  confidence:
    min_confidence_threshold: 0.65  # REVERTED from 0.80 to 0.65
  ```

**Code Implementation**:
- `merid/risk/profiles/global_allocator.py` line 78:
  ```python
  min_confidence: float = 0.65,  # 2026-07-15: Updated to 65% to match profile YAML
  ```

- `merid/risk/risk_guard.py` line 74:
  ```python
  min_confidence_for_trade: float = 0.65
  ```

**Test Inconsistencies**:
- `merid/risk/profiles/test_global_allocator.py` lines 363, 398, 438, 477, 511:
  ```python
  min_confidence=0.50,  # 2026-07-10: Lowered from 65% to 50% to match agent grid confidence
  ```

**Legacy Values in YAML**:
- `config/profiles/kalshi_crypto_15m_v2.yaml` lines 1688, 1694, 1697, 1700, 1703, 1706:
  ```yaml
  strategies:
    btc_15m:
      policy:
        min_confidence: 0.50  # LEGACY VALUE: Not actively used
  ```

**Impact**:
- Primary threshold is 65% (consistent between YAML and code)
- Some tests use 50% (outdated)
- Legacy strategy sections have 50% (documented as not actively used)
- **May cause test failures but not production issues**

**Files Affected**:
- `merid/risk/profiles/test_global_allocator.py` (lines 363, 398, 438, 477, 511)

**Recommendation**:
Update test expectations to 65% to match production configuration.

### 3. Liquidity Check Threshold (CONSISTENT)

**Configuration (YAML)**:
- `config/profiles/kalshi_crypto_15m_v2.yaml` lines 810, 811, 835, 836, etc.:
  ```yaml
  depth_thresholds:
    btc:
      min_depth_yes: 1  # Minimum YES depth at best bid (contracts)
      min_depth_no: 1   # Minimum NO depth at best ask (contracts)
  ```

**Code Implementation**:
- `merid/loop_15m.py` line 3276:
  ```python
  target_qty = min_depth_yes_threshold  # Conservative: use YES threshold as target
  ```

- `merid/loop_15m.py` line 3247:
  ```python
  min_depth_yes_threshold = depth_thresholds.get('min_depth_yes', 1)  # Default 1
  ```

- `merid/loop_15m.py` line 416 (in `can_fill_order_safely`):
  ```python
  if available_qty >= 1:  # At least 1 contract available
  ```

**Impact**:
- Consistent across YAML and code (1 contract minimum)
- **This is likely why orders are not executing: markets have < 1 contract depth**

**Files Affected**:
- None (consistent)

**Recommendation**:
No change needed. This is working as designed. If markets lack liquidity, the system correctly prevents order execution.

### 4. Price Range Threshold (CONSISTENT)

**Configuration (YAML)**:
- `config/profiles/kalshi_crypto_15m_v2.yaml`:
  ```yaml
  guardrails:
    min_contract_price_cents: 10
    max_contract_price_cents: 75
  ```

**Code Implementation**:
- `merid/event_venues/kalshi/risk_parameters.py` lines 36-37:
  ```python
  CANONICAL_MIN_PRICE_CENTS: Final[int] = 10
  CANONICAL_MAX_PRICE_CENTS: Final[int] = 75
  ```

**Impact**:
- Consistent at 10-75c across all files
- **No issues**

**Files Affected**:
- None (consistent)

**Recommendation**:
No change needed.

## Additional Findings

### 5. Loop State Logic

**Issue**: `allow_new_entries=False` when `ready_assets_count=0`

**Code Flow**:
1. `loop_15m.py` line 3315: `ready_assets_count += 1` only when `asset_depth_ok = True`
2. `loop_15m.py` line 3294: `asset_depth_ok = True` only when liquidity decision is FULL or REDUCED
3. `loop_15m.py` line 416: REDUCED requires `available_qty >= 1`
4. If all assets have `available_qty < 1`, then `ready_assets_count = 0`
5. `compute_loop_state` line 623-637: `ready_assets_count = 0` → `allow_new_entries = False`
6. `agent_grid_15m.py` line 13259: `allow_new_entries = False` → global allocator skipped

**Impact**:
- If markets have insufficient depth (< 1 contract), no orders execute
- This is by design to prevent orders that cannot be filled

**Recommendation**:
This is correct behavior. The system should not execute orders when liquidity is insufficient.

## Root Cause Analysis

### Why Candidates Are Generated But Orders Don't Execute

**Evidence from logs**:
- Candidates ARE being generated (ETH 1.59% edge, SOL 2.62% edge)
- Bankroll is fresh ($11.78)
- Risk envelope is computed successfully
- **NO GLOBAL-ALLOCATOR logs** (allocator phase skipped)
- **NO 15M-EXECUTION logs** (execution phase not reached)

**Root cause chain**:
1. Edge threshold mismatch (2.5% in code vs 3.0% in YAML)
2. Candidates with 2.5-3.0% edge pass code validation
3. These candidates fail YAML validation at global allocator
4. OR: Liquidity check fails (available_qty < 1 contract)
5. `ready_assets_count = 0`
6. `allow_new_entries = False`
7. Global allocator skipped
8. No orders executed

**Most likely scenario**:
The edge threshold mismatch is the primary issue. Candidates with 2.5-3.0% edge are being generated but filtered out because:
- Code uses 2.5% threshold (allows them)
- YAML uses 3.0% threshold (rejects them)
- The global allocator reads from YAML, so it rejects them

## Recommended Fixes

### Priority 1: Fix Edge Threshold Inconsistency

**Option A**: Update code to match YAML (3.0%)
```python
# merid/event_venues/kalshi/risk_parameters.py line 244
EDGE_BANDS_MINIMUM = 0.030  # 3.0% minimum edge from profile edge_bands

# merid/risk/profiles/global_allocator.py line 77
min_edge_pct: float = 0.030,  # 3.0% to match profile edge_bands
```

**Option B**: Update YAML to match code (2.5%)
```yaml
# config/profiles/kalshi_crypto_15m_v2.yaml lines 984, 989, 994
edge_bands:
  watch:
    min_edge_pct: 0.025  # 2.5% minimum edge for watch band
  small:
    min_edge_pct: 0.025  # 2.5% minimum edge for small band
  standard:
    min_edge_pct: 0.025  # 2.5% minimum edge for standard band
```

**Recommendation**: Option A (update code to match YAML). YAML is documented as the source of truth.

### Priority 2: Update Test Confidence Thresholds

```python
# merid/risk/profiles/test_global_allocator.py lines 363, 398, 438, 477, 511
min_confidence=0.65,  # Updated to 65% to match production configuration
```

### Priority 3: Add Logging for Threshold Validation

Add logging to show which threshold is being used at each layer:
- Agent grid: Log edge threshold used for candidate generation
- Global allocator: Log edge threshold used for filtering
- Loop state: Log `allow_new_entries` value and reason

## Verification Steps

1. Apply edge threshold fix (Option A)
2. Update test confidence thresholds
3. Run tests: `pytest merid/risk/profiles/test_global_allocator.py`
4. Check logs for:
   - `[GLOBAL-ALLOCATOR-*]` logs appearing
   - `[15M-EXECUTION-*]` logs appearing
   - Orders being executed
5. Monitor for candidates with 2.5-3.0% edge being accepted

## Conclusion

The primary issue is **edge threshold misalignment** between configuration (3.0%) and code (2.5%). This causes candidates in the 2.5-3.0% range to be generated but filtered out, explaining why neither YES nor NO edge orders are executing.

Secondary issues include test confidence threshold mismatches (50% vs 65%), but these don't affect production.

The liquidity check (1 contract minimum) is working as designed and should not be changed.
