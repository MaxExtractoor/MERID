# Hedge Config Consolidation Review

**Created:** 2026-07-07  
**Purpose:** Review options for consolidating hedge configurations into single source of truth

---

## Executive Summary

**Recommendation:** Keep hedge configs separate (current state).

**Rationale:**
1. Offset hedging and CryptoHedgeEngine serve different purposes
2. Separation provides clear architectural boundaries
3. Profile YAML is already large; adding hedge config would increase complexity
4. Separate configs allow independent evolution of each system

---

## Current State

### Config File 1: Profile YAML

**File:** `config/profiles/kalshi_crypto_15m_v2.yaml`

**Hedging Section:**
```yaml
offset_hedging:
  enabled: false  # DISABLED for crypto
  hedge_ratio: 0.30  # 30% hedge ratio if enabled
```

**Purpose:** 
- Profile-level flag for offset hedging
- Controls whether prediction market positions are hedged against spot/derivatives
- Single boolean flag with hedge ratio

**Size:** 558 lines total (hedging section: 3 lines)

### Config File 2: Hedge Config YAML

**File:** `config/kalshi_crypto_hedging.yaml`

**Full Structure:**
```yaml
hedging:
  enabled: true
  use_cross_asset_hedging: false
  max_drawdown_pct: 40.0

  asset_slices:
    BTC:
      slice_pct_of_bankroll: 0.20
      per_trade_risk_pct_of_slice: 1.0
      max_drawdown_pct_of_slice: 3.0
    # ... ETH, SOL, XRP, DOGE

  timeframes:
    15m:
      max_net_exposure_pct_of_slice: 10.0
      target_hedge_ratio: 0.5
      prefer_same_timeframe: true
      allow_adjacent_horizons: []

  cross_asset:
    enabled: false
    max_pair_correlation: 0.85
    max_cross_hedge_pct_of_base: 0.20
    pairs: []

  take_profit:
    enabled: true
    BTC:
      tp_1: 2.0
      tp_2: 4.0
      stop_loss: 1.5
    # ... other assets

  auto_exit:
    enabled: true
    close_hedge_when_alpha_closed: true
    max_hedge_hold_minutes: 120
    reduce_on_exposure_flip: true
```

**Purpose:**
- Full configuration for CryptoHedgeEngine
- Asset-specific bankroll slices
- Timeframe-specific hedge rules
- Cross-asset hedging parameters
- Take profit configuration
- Auto-exit configuration

**Size:** 77 lines

---

## Consolidation Options

### Option 1: Merge into Profile YAML

**Approach:** Add full hedge config to profile YAML

**Proposed Structure:**
```yaml
# config/profiles/kalshi_crypto_15m_v2.yaml

# ... existing profile config ...

# Offset hedging (prediction markets)
offset_hedging:
  enabled: false
  hedge_ratio: 0.30

# CryptoHedgeEngine configuration
crypto_hedge_engine:
  enabled: true
  use_cross_asset_hedging: false
  max_drawdown_pct: 40.0
  
  asset_slices:
    BTC:
      slice_pct_of_bankroll: 0.20
      per_trade_risk_pct_of_slice: 1.0
      max_drawdown_pct_of_slice: 3.0
    # ... other assets
  
  timeframes:
    15m:
      max_net_exposure_pct_of_slice: 10.0
      target_hedge_ratio: 0.5
      prefer_same_timeframe: true
      allow_adjacent_horizons: []
  
  cross_asset:
    enabled: false
    max_pair_correlation: 0.85
    max_cross_hedge_pct_of_base: 0.20
    pairs: []
  
  take_profit:
    enabled: true
    BTC:
      tp_1: 2.0
      tp_2: 4.0
      stop_loss: 1.5
    # ... other assets
  
  auto_exit:
    enabled: true
    close_hedge_when_alpha_closed: true
    max_hedge_hold_minutes: 120
    reduce_on_exposure_flip: true
```

**Pros:**
- Single source of truth for all configuration
- Easier to see all settings in one place
- Reduces config file count

**Cons:**
- Profile YAML becomes very large (558 → 635+ lines)
- Mixes different concerns (profile risk parameters vs. hedge engine rules)
- Profile adapter becomes more complex
- Harder to maintain separation of concerns
- Changes to hedge config require profile reload

**Implementation Effort:** 2-3 hours
- Update profile YAML structure
- Update profile adapter to load hedge config
- Update hedge config loader to read from profile
- Update all tests
- Update documentation

---

### Option 2: Keep Separate (Current State)

**Approach:** Maintain two separate config files

**Current Structure:**
- `config/profiles/kalshi_crypto_15m_v2.yaml` - Profile risk parameters + offset hedging flag
- `config/kalshi_crypto_hedging.yaml` - CryptoHedgeEngine configuration

**Pros:**
- Clear separation of concerns
- Profile YAML stays focused on risk parameters
- Hedge config can evolve independently
- Easier to understand architecture
- Changes to hedge config don't require profile reload
- Smaller, more focused config files

**Cons:**
- Two config files to manage
- Need to remember which file to edit for which setting
- Slightly more complex file structure

**Implementation Effort:** 0 hours (current state)

---

### Option 3: Hybrid Approach

**Approach:** Profile flags only, detailed config separate

**Proposed Structure:**

**Profile YAML:**
```yaml
# config/profiles/kalshi_crypto_15m_v2.yaml

# Offset hedging (prediction markets)
offset_hedging:
  enabled: false
  hedge_ratio: 0.30

# CryptoHedgeEngine flags only
crypto_hedge_engine:
  enabled: true
  config_path: "config/kalshi_crypto_hedging.yaml"
```

**Hedge Config YAML:**
```yaml
# config/kalshi_crypto_hedging.yaml (unchanged)
```

**Pros:**
- Profile has enable/disable flags for both systems
- Detailed hedge config remains separate
- Clear separation of concerns
- Profile controls which systems are active
- Hedge config can be versioned independently

**Cons:**
- Still two config files
- Slightly more complex than current state
- Need to maintain config path reference

**Implementation Effort:** 1 hour
- Add crypto_hedge_engine section to profile YAML
- Update profile adapter to load hedge config path
- Update hedge config loader to use path from profile
- Update tests
- Update documentation

---

## Recommendation Analysis

### Criteria 1: Separation of Concerns

**Offset Hedging:**
- Purpose: Hedge prediction market positions
- Scope: Profile-level flag only
- Integration: Profile adapter, risk envelope
- Complexity: Low (boolean flag + ratio)

**CryptoHedgeEngine:**
- Purpose: Rule-based hedging for crypto positions
- Scope: Multi-asset, multi-timeframe
- Integration: Dedicated engine, API endpoints
- Complexity: High (asset slices, timeframes, TP/SL, auto-exit)

**Assessment:** These are fundamentally different systems with different purposes and complexity. Separation is appropriate.

### Criteria 2: Maintainability

**Option 1 (Merge):**
- Profile YAML becomes 15% larger
- Profile adapter becomes more complex
- Harder to find specific settings
- Risk of accidental changes to unrelated sections

**Option 2 (Separate):**
- Each file has clear purpose
- Easier to find specific settings
- Changes isolated to relevant system
- Lower risk of accidental changes

**Option 3 (Hybrid):**
- Profile has flags only
- Detailed config separate
- Clear separation
- Slightly more complex than Option 2

**Assessment:** Option 2 (separate) provides best maintainability.

### Criteria 3: Flexibility

**Option 1 (Merge):**
- Hedge config changes require profile reload
- Cannot version hedge config independently
- All changes must go through profile adapter

**Option 2 (Separate):**
- Hedge config changes don't require profile reload
- Can version hedge config independently
- Hedge config loader is independent

**Option 3 (Hybrid):**
- Profile controls enable/disable
- Hedge config can be changed independently
- Best of both worlds

**Assessment:** Option 3 (hybrid) provides best flexibility, but Option 2 is sufficient.

### Criteria 4: Clarity

**Option 1 (Merge):**
- All settings in one place
- But file becomes large and complex
- Harder to understand architecture

**Option 2 (Separate):**
- Clear file boundaries
- Easy to understand which file to edit
- Architecture is clear

**Option 3 (Hybrid):**
- Profile has high-level flags
- Detailed config separate
- Clear architecture

**Assessment:** Option 2 and Option 3 both provide clarity. Option 2 is simpler.

---

## Final Recommendation

**Keep configs separate (Option 2 - Current State)**

### Rationale

1. **Clear Separation of Concerns**
   - Offset hedging is a simple profile flag
   - CryptoHedgeEngine is a complex system with its own config
   - Different purposes, different complexity, different files

2. **Best Maintainability**
   - Each file has a clear, focused purpose
   - Changes are isolated to relevant system
   - Lower risk of accidental changes

3. **Sufficient Flexibility**
   - Hedge config can be changed independently
   - No need for profile reload when changing hedge settings
   - Independent versioning possible

4. **Simplest Architecture**
   - No changes required
   - Current state works well
   - No additional complexity

### When to Reconsider

Consolidation may be appropriate if:

1. **Number of Config Files Grows**
   - If more hedging systems are added
   - If config file count becomes unmanageable

2. **Profile Becomes Larger Anyway**
   - If profile YAML grows significantly for other reasons
   - If adding hedge config is marginal relative to total size

3. **Unified Config Management Needed**
   - If a config management system is implemented
   - If single source of truth becomes critical for operations

---

## Alternative: Document the Separation

If separation is maintained, improve documentation:

1. **Add Cross-References**
   - In profile YAML, add comment: "See kalshi_crypto_hedging.yaml for CryptoHedgeEngine config"
   - In hedge config YAML, add comment: "See kalshi_crypto_15m_v2.yaml for profile config"

2. **Update Architecture Doc**
   - Already documented in `docs/HEDGING_SYSTEM_ARCHITECTURE.md`
   - Ensure this doc is referenced in main README

3. **Add Config Index**
   - Create `docs/CONFIGURATION_INDEX.md` listing all config files and their purposes
   - Include cross-references between related configs

**Implementation Effort:** 30 minutes

---

## Current Status Summary

**Config Files:**
- `config/profiles/kalshi_crypto_15m_v2.yaml` (558 lines) - Profile risk parameters + offset hedging flag
- `config/kalshi_crypto_hedging.yaml` (77 lines) - CryptoHedgeEngine configuration

**Loaders:**
- `merid/risk/profiles/crypto_15m_profile.py` - Loads profile YAML
- `merid/hedging/config.py` - Loads hedge config YAML

**Recommendation:** Keep separate (current state).

---

## Next Steps

1. **Document Decision**
   - Update `docs/HEDGING_SYSTEM_ARCHITECTURE.md` with consolidation review results
   - Add config cross-references to YAML files

2. **Create Config Index**
   - Create `docs/CONFIGURATION_INDEX.md` listing all config files
   - Include purposes and cross-references

3. **Monitor Config Growth**
   - Track if number of config files grows significantly
   - Reassess consolidation if config management becomes complex

---

## References

**Related Documentation:**
- `docs/HEDGING_SYSTEM_ARCHITECTURE.md` - Dual hedging system overview
- `config/profiles/kalshi_crypto_15m_v2.yaml` - Profile configuration
- `config/kalshi_crypto_hedging.yaml` - Hedge engine configuration

**Key Files:**
- `merid/risk/profiles/crypto_15m_profile.py` - Profile adapter
- `merid/hedging/config.py` - Hedge config loader
