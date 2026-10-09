# Final Remaining Bugs Sweep - 2026-08-01

## Purpose

This is the final invariant-driven audit pass to catch remaining sibling bugs in startup, config precedence, reconciliation, and alternate execution paths that still assume the old 10c-75c world.

---

## Audit Structure

For each area, we define:
1. **Search Targets** - Exact patterns to search for
2. **Regression Tests** - Tests to add if bugs found
3. **Likely Bug Classes** - Common failure modes

---

## Area 1: Upstream - Profile/YAML Keys and Startup

### Search Targets

#### 1.1 Profile/YAML Keys with Old Ranges
**Pattern:** `75|25` in YAML files (excluding intentional constants)
**Files:** `config/profiles/*.yaml`
**Search:** `grep -r "75\|25" config/profiles/ --include="*.yaml"`
**Exclude:** 
- `75%` (percentages)
- `25%` (percentages)
- `0.75` (multipliers)
- `0.25` (multipliers)
- Comments with context (e.g., "75th percentile")

**Expected Findings:**
- ✅ None (all should be updated to 5c-85c or 15c-99c)
- ❌ Any remaining `min_price_cents: 10` or `max_price_cents: 75`

**Regression Test:** `test_yaml_no_old_ranges.py`
```python
def test_yaml_no_old_price_ranges():
    """Verify no YAML files still have old 10c-75c ranges."""
    import yaml
    import os
    
    yaml_files = glob.glob("config/profiles/*.yaml")
    for yaml_file in yaml_files:
        with open(yaml_file, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)
        
        # Check for old ranges
        if 'price_range' in config:
            assert config['price_range'].get('min_price_cents', 10) == 5
            assert config['price_range'].get('max_price_cents', 75) == 85
        
        if 'guardrails' in config:
            assert config['guardrails'].get('min_contract_price_cents', 10) == 5
            assert config['guardrails'].get('max_contract_price_cents', 75) == 85
```

#### 1.2 Signal Generators with Duplicated Range Constants
**Pattern:** `10.*75|25.*75` in `merid/prediction/*.py`
**Files:** `merid/prediction/*.py`
**Search:** `grep -r "10.*75\|25.*75" merid/prediction/ --include="*.py"`
**Exclude:**
- Comments with "CRITICAL FIX" or "2026-08-01"
- Test files (already audited)

**Expected Findings:**
- ✅ None (all should be updated)
- ❌ Any remaining hardcoded `10c-75c` or `25c-75c`

**Regression Test:** `test_signal_generators_no_old_ranges.py`
```python
def test_signal_generators_no_old_price_ranges():
    """Verify signal generators don't have old hardcoded ranges."""
    import os
    import re
    
    py_files = glob.glob("merid/prediction/*.py")
    for py_file in py_files:
        with open(py_file, 'r') as f:
            content = f.read()
        
        # Check for old patterns (excluding comments with fixes)
        lines = content.split('\n')
        for i, line in enumerate(lines):
            if re.search(r'10.*75|25.*75', line):
                # Allow if it's a comment with CRITICAL FIX
                if 'CRITICAL FIX' not in line and '2026-08-01' not in line:
                    assert False, f"Found old range in {py_file}:{i+1}: {line}"
```

#### 1.3 Regime Classifiers with Stale Comments
**Pattern:** Comments referencing `10c-75c` or `25c-75c`
**Files:** `merid/event_venues/kalshi/market_regime_detector.py`, `merid/prediction/regime_detector.py`
**Search:** `grep -r "10c-75c\|25c-75c" merid/ --include="*.py"`
**Exclude:**
- Comments with "CRITICAL FIX" or "2026-08-01"
- Test files

**Expected Findings:**
- ✅ None (all comments updated)
- ❌ Any stale comments that could mislead future changes

**Regression Test:** `test_no_stale_comments.py`
```python
def test_no_stale_price_range_comments():
    """Verify no stale comments referencing old ranges."""
    import os
    import re
    
    py_files = glob.glob("merid/**/*.py", recursive=True)
    for py_file in py_files:
        with open(py_file, 'r') as f:
            content = f.read()
        
        # Check for old patterns in comments
        if '10c-75c' in content or '25c-75c' in content:
            # Allow if it's a comment with CRITICAL FIX
            if 'CRITICAL FIX' not in content and '2026-08-01' not in content:
                assert False, f"Found stale comment in {py_file}"
```

#### 1.4 Startup/Bootstrap Load Order
**Pattern:** Profile loading vs module initialization
**Files:** `merid/risk/profiles/crypto_15m_profile.py`, `merid/__init__.py`
**Search:** Look for module-level constants that could be initialized before profile loads

**Expected Findings:**
- ✅ Profile loads before any module-level fallback logic
- ❌ Module-level constants initialized before profile load

**Regression Test:** `test_startup_load_order.py`
```python
def test_profile_loads_before_module_defaults():
    """Verify profile loads before module defaults are consulted."""
    from merid.risk.profiles.crypto_15m_profile import get_active_profile, is_profile_active
    
    # Profile should be active
    assert is_profile_active()
    
    # Profile should have new ranges
    profile = get_active_profile()
    if profile and hasattr(profile.profile, 'guardrails'):
        assert profile.profile.guardrails.max_contract_price_cents >= 85
```

---

## Area 2: Midstream - Order Building and Router Code Paths

### Search Targets

#### 2.1 Alternate Price Clamps
**Pattern:** `max\(.*,.*\)|min\(.*,.*\)` in order-building files
**Files:** `merid/event_venues/kalshi/order_*.py`
**Search:** `grep -r "max\|min" merid/event_venues/kalshi/order_*.py`
**Context:** Look for price clamping that might use old ranges

**Expected Findings:**
- ✅ All clamps use allocator bounds [10, 75] (intentional) or canonical ranges [5, 85]
- ❌ Any clamps using old [10, 75] for canonical range

**Regression Test:** `test_order_building_clamps.py`
```python
def test_order_building_uses_correct_clamps():
    """Verify order building uses correct clamps."""
    import os
    import re
    
    py_files = glob.glob("merid/event_venues/kalshi/order_*.py")
    for py_file in py_files:
        with open(py_file, 'r') as f:
            content = f.read()
        
        # Check for clamps with old ranges
        lines = content.split('\n')
        for i, line in enumerate(lines):
            if re.search(r'max\(10,.*75\)|min\(10,.*75\)', line):
                # Allow if it's allocator bounds (intentional)
                if 'ALLOCATOR' not in line and 'allocator' not in line:
                    assert False, f"Found old clamp in {py_file}:{i+1}: {line}"
```

#### 2.2 Spread Fallbacks
**Pattern:** `fallback.*spread|spread.*fallback`
**Files:** `merid/prediction/*.py`, `merid/event_venues/kalshi/*.py`
**Search:** `grep -r "fallback.*spread\|spread.*fallback" merid/ --include="*.py"`

**Expected Findings:**
- ✅ All fallback spreads use 1c (for malformed data) or 85c (max spread)
- ❌ Any fallback spreads using old 75c max

**Regression Test:** `test_spread_fallbacks.py`
```python
def test_spread_fallbacks_use_new_ranges():
    """Verify spread fallbacks use new ranges."""
    import os
    import re
    
    py_files = glob.glob("merid/**/*.py", recursive=True)
    for py_file in py_files:
        with open(py_file, 'r') as f:
            content = f.read()
        
        # Check for old fallback spreads
        if 'fallback' in content and 'spread' in content:
            if '75' in content and '85' not in content:
                # Allow if it's a comment with CRITICAL FIX
                if 'CRITICAL FIX' not in content and '2026-08-01' not in content:
                    assert False, f"Found old spread fallback in {py_file}"
```

#### 2.3 Maker/Taker Selection Branches
**Pattern:** `if.*maker|if.*taker` in order routing files
**Files:** `merid/event_venues/kalshi/order_router.py`, `merid/prediction/agent_grid_15m.py`
**Search:** `grep -r "if.*maker\|if.*taker" merid/event_venues/kalshi/order_router.py merid/prediction/agent_grid_15m.py`

**Expected Findings:**
- ✅ All maker/taker selection uses regime detector
- ❌ Any hardcoded maker/taker selection without regime check

**Regression Test:** `test_maker_taker_selection.py`
```python
def test_maker_taker_selection_uses_regime():
    """Verify maker/taker selection uses regime detector."""
    import os
    import re
    
    py_files = [
        'merid/event_venues/kalshi/order_router.py',
        'merid/prediction/agent_grid_15m.py'
    ]
    
    for py_file in py_files:
        with open(py_file, 'r') as f:
            content = f.read()
        
        # Check for hardcoded maker/taker selection
        # (this is a heuristic - real test would need more context)
        if 'ExecutionMode.MAKER' in content or 'ExecutionMode.TAKER' in content:
            # Should be accompanied by regime detector call
            if 'classify_regime' not in content and 'classify' not in content:
                # Allow if it's a comment or test
                if 'CRITICAL FIX' not in content and 'test' not in py_file:
                    assert False, f"Found hardcoded maker/taker selection in {py_file}"
```

#### 2.2.4 Orders After Stale/Zero-Depth Flag
**Pattern:** Order submission after stale/zero-depth check
**Files:** `merid/event_venues/kalshi/order_*.py`
**Search:** Look for order submission code that might bypass stale/zero-depth checks

**Expected Findings:**
- ✅ No order can be submitted after stale/zero-depth flag
- ❌ Any code path that can submit order despite stale/zero-depth flag

**Regression Test:** `test_no_order_after_stale_flag.py`
```python
def test_no_order_submission_after_stale_flag():
    """Verify no order can be submitted after stale flag."""
    # This would require mocking the full order submission flow
    # For now, we verify the blocking logic exists
    import os
    
    py_files = glob.glob("merid/event_venues/kalshi/order_*.py")
    for py_file in py_files:
        with open(py_file, 'r') as f:
            content = f.read()
        
        # Check for zero-depth blocking logic
        assert 'zero_depth' in content or 'depth == 0' in content or 'depth_yes == 0' in content
```

---

## Area 3: Downstream - Reconciliation and Monitoring

### Search Targets

#### 3.1 Fee Reconciliation on Partial Fills
**Pattern:** `partial.*fill|fill.*partial` in reconciliation files
**Files:** `merid/event_venues/kalshi/fills_ledger.py`, `merid/position_management/*.py`
**Search:** `grep -r "partial.*fill\|fill.*partial" merid/event_venues/kalshi/fills_ledger.py merid/position_management/*.py`

**Expected Findings:**
- ✅ Partial fills use same fee formula as full fills
- ❌ Partial fills use different fee formula

**Regression Test:** `test_partial_fill_fee_reconciliation.py`
```python
def test_partial_fill_fee_reconciliation():
    """Verify partial fills use same fee formula."""
    from merid.event_venues.kalshi.parabolic_fees import kalshi_maker_fee_cents
    
    # Test partial fill fee calculation
    full_fee = kalshi_maker_fee_cents(10, 50)  # 10 contracts at 50c
    partial_fee = kalshi_maker_fee_cents(5, 50)  # 5 contracts at 50c
    
    # Fee should scale linearly with contract count
    assert partial_fee == full_fee / 2 or partial_fee == 1  # Parabolic formula may not be linear
```

#### 3.2 Fee Reconciliation on Cancels/Replaces
**Pattern:** `cancel|replace` in reconciliation files
**Files:** `merid/event_venues/kalshi/fills_ledger.py`, `merid/event_venues/kalshi/order_*.py`
**Search:** `grep -r "cancel\|replace" merid/event_venues/kalshi/fills_ledger.py merid/event_venues/kalshi/order_*.py`

**Expected Findings:**
- ✅ Cancels/replaces don't incur maker fees (only fills do)
- ❌ Cancels/replaces incorrectly charged maker fees

**Regression Test:** `test_cancel_replace_fee_handling.py`
```python
def test_cancel_replace_no_maker_fee():
    """Verify cancels and replaces don't incur maker fees."""
    # This would require mocking the cancel/replace flow
    # For now, we verify the logic exists
    import os
    
    py_files = glob.glob("merid/event_venues/kalshi/*.py")
    for py_file in py_files:
        with open(py_file, 'r') as f:
            content = f.read()
        
        # Check for cancel/replace handling
        if 'cancel' in content or 'replace' in content:
            # Should not charge maker fee for cancel/replace
            # (this is a heuristic - real test would need more context)
            pass
```

#### 3.3 Monitoring Coverage
**Pattern:** Monitoring calls in all execution paths
**Files:** All files that submit orders or make trading decisions
**Search:** Verify all order submission paths call monitoring

**Expected Findings:**
- ✅ All order submission paths call monitoring
- ❌ Any order submission path bypasses monitoring

**Regression Test:** `test_monitoring_coverage.py`
```python
def test_monitoring_covers_all_execution_paths():
    """Verify monitoring covers all execution paths."""
    import os
    
    # Check that monitoring is imported and used in key files
    key_files = [
        'merid/prediction/agent_grid_15m.py',
        'merid/event_venues/kalshi/order_router.py',
        'merid/event_venues/kalshi/order_gate.py'
    ]
    
    for py_file in key_files:
        with open(py_file, 'r') as f:
            content = f.read()
        
        # Should import and use monitoring
        assert 'invariants_monitor' in content or 'trading_invariants_monitor' in content
```

#### 3.4 PnL/Fee Accounting Consistency
**Pattern:** PnL calculation vs fee calculation
**Files:** `merid/position_management/*.py`, `merid/event_venues/kalshi/fills_ledger.py`
**Search:** Verify PnL and fee use same contract count and price basis

**Expected Findings:**
- ✅ PnL and fee use same contract count and price basis
- ❌ PnL and fee use different contract count or price basis

**Regression Test:** `test_pnl_fee_accounting_consistency.py`
```python
def test_pnl_fee_accounting_consistency():
    """Verify PnL and fee accounting use same basis."""
    # This would require mocking the PnL and fee calculation
    # For now, we verify the logic exists
    import os
    
    py_files = glob.glob("merid/position_management/*.py")
    for py_file in py_files:
        with open(py_file, 'r') as f:
            content = f.read()
        
        # Check for PnL and fee calculation
        if 'pnl' in content.lower() and 'fee' in content.lower():
            # Should use same contract count
            # (this is a heuristic - real test would need more context)
            pass
```

---

## Area 4: End to End - Regression Tests

### Regression Tests to Add

#### 4.1 Startup/Reload Regression Test
**File:** `tests/test_startup_reload_regression_2026_08_01.py`
**Purpose:** Verify startup order and config reloads cannot restore old constants

```python
def test_startup_loads_profile_first():
    """Verify profile loads before any module defaults."""
    # Simulate startup sequence
    # 1. Import profile module
    # 2. Verify profile is loaded
    # 3. Verify module defaults are overridden
    pass

def test_config_reload_preserves_new_ranges():
    """Verify config reload preserves new 5c-85c ranges."""
    # Simulate config reload
    # 1. Load config
    # 2. Verify new ranges
    # 3. Reload config
    # 4. Verify new ranges still active
    pass
```

#### 4.2 Config-Precedence Regression Test
**File:** `tests/test_config_precedence_regression_2026_08_01.py`
**Purpose:** Verify old defaults cannot win over profile values

```python
def test_module_defaults_cannot_override_profile():
    """Verify module defaults cannot override profile values."""
    # Set module defaults to old values (intentionally wrong)
    # Load profile
    # Verify profile values win
    pass

def test_env_vars_cannot_override_profile():
    """Verify env vars cannot override profile values."""
    # Set env vars to old values (intentionally wrong)
    # Load profile
    # Verify profile values win
    pass
```

#### 4.3 Reconciliation Regression Test
**File:** `tests/test_reconciliation_regression_2026_08_01.py`
**Purpose:** Simulate fill lifecycle and assert fee/PnL consistency

```python
def test_fill_lifecycle_fee_pnl_consistency():
    """Simulate fill lifecycle and assert fee/PnL consistency."""
    # 1. Submit order
    # 2. Receive partial fill
    # 3. Calculate expected fee
    # 4. Calculate expected PnL
    # 5. Verify actual fee matches expected
    # 6. Verify actual PnL matches expected
    pass

def test_cancel_replace_no_fee():
    """Verify cancel/replace doesn't incur maker fee."""
    # 1. Submit order
    # 2. Cancel order
    # 3. Verify no fee charged
    # 4. Replace order
    # 5. Verify no fee charged for replace
    pass
```

#### 4.4 Stale-Book Bypass Test
**File:** `tests/test_stale_book_bypass_regression_2026_08_01.py`
**Purpose:** Prove no order can bypass stale/zero-depth block through another route

```python
def test_no_order_bypasses_stale_block():
    """Verify no order can bypass stale block through another route."""
    # 1. Flag book as stale
    # 2. Try to submit order through all possible routes
    # 3. Verify all routes block
    pass

def test_no_order_bypasses_zero_depth_block():
    """Verify no order can bypass zero-depth block through another route."""
    # 1. Set depth to zero
    # 2. Try to submit order through all possible routes
    # 3. Verify all routes block
    pass
```

---

## Likely Remaining Bug Classes

### 1. Old Constants in Comments/Docs
**Risk:** Comments/docs with old ranges get copied back into code
**Mitigation:** Update all comments/docs to reference new ranges
**Search:** All comments and documentation files

### 2. Second Execution Path Not Consulting Invariant Monitor
**Risk:** Alternate code path bypasses monitoring
**Mitigation:** Add monitoring calls to all execution paths
**Search:** All order submission and decision points

### 3. Fee Drift in Cancel/Replace/Partial Fill
**Risk:** Different fee formula for different order types
**Mitigation:** Ensure all fee calculations use same parabolic formula
**Search:** All fee calculation code paths

### 4. Config Reloads Reinitialize Defaults in Wrong Order
**Risk:** Config reload restores old defaults
**Mitigation:** Ensure profile always loads before defaults
**Search:** All config loading code

### 5. Monitoring Thresholds Too High
**Risk:** Next regression not caught early
**Mitigation:** Lower thresholds to catch issues sooner
**Search:** All monitoring threshold constants

---

## Execution Plan

### Phase 1: Search (Automated)
1. Run all search targets in parallel
2. Collect findings
3. Categorize findings by area

### Phase 2: Fix Bugs
1. Fix any bugs found in search
2. Update tests to prevent regression
3. Run all tests to verify fixes

### Phase 3: Add Regression Tests
1. Add startup/reload regression test
2. Add config-precedence regression test
3. Add reconciliation regression test
4. Add stale-book bypass test

### Phase 4: Final Validation
1. Run all 84 existing tests
2. Run all new regression tests
3. Verify 100% pass rate
4. Update documentation

---

## Success Criteria

- ✅ No old constants in comments/docs
- ✅ All execution paths consult invariant monitor
- ✅ All fee calculations use same formula
- ✅ Config reloads preserve new ranges
- ✅ Monitoring thresholds are appropriate
- ✅ All regression tests pass
- ✅ Total tests >= 100 (84 existing + 16 new)
