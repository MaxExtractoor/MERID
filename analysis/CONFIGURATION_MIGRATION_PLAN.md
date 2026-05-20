# Configuration Migration Plan

**Date:** 2026-05-13
**Purpose:** Detailed migration plan from legacy configuration to canonical profile-based system

## Canonical Configuration Decision

**Chosen System:** Profile-based configuration
**Primary File:** `config/profiles/kalshi_crypto_15m.yaml`
**Activation:** `MERID_PROFILE=kalshi_crypto_15m_v2`

**Rationale:**
- Single source of truth for risk parameters
- Config-only behavior (no bankroll derivation)
- Explicit caps and limits
- Already adopted in parts of the codebase
- Well-documented and tested

**Supporting Canonical Files:**
- `config/crypto_threshold_matrix.yaml` - Baseline edge thresholds
- `config/kalshi_crypto_config.py` - Asset/frequency constants
- `config/kalshi_agent_grid.yaml` - Agent definitions only (simplified)

## Migration Phases

### Phase 1: Complete Profile Adoption (HIGH PRIORITY)

**Objective:** Move all risk limits from agent grid to profile

**Steps:**
1. **Move entry window parameters to profile**
   - Move `minutes_before_expiry` and `cutoff_minutes_before_expiry` from agent grid to profile agent_defaults
   - Update profile to include these parameters for all assets
   - Remove entry_window sections from kalshi_agent_grid.yaml

2. **Move take profit parameters to profile**
   - Extract take_profit configuration from agent grid
   - Add to profile as agent_defaults or per-asset overrides
   - Remove take_profit sections from kalshi_agent_grid.yaml

3. **Remove PROFILE-GATED comments from agent grid**
   - Remove all PROFILE-GATED comments from kalshi_agent_grid.yaml
   - Remove risk_limits sections from agent grid (now in profile)
   - Remove strategy edge thresholds from agent grid (now in profile/threshold matrix)
   - Keep only: name, series_tickers, assets, timeframes, archetype, market_filter

4. **Update profile activation**
   - Make profile mandatory for 15m crypto trading
   - Add validation to ensure profile is loaded before agent grid
   - Add error if profile not found when 15m crypto agents are enabled

**Files to Modify:**
- `config/profiles/kalshi_crypto_15m.yaml` - Add entry window and take profit parameters
- `config/kalshi_agent_grid.yaml` - Remove risk_limits, strategy, entry_window, take_profit sections
- `merid/prediction/agent_grid_config.py` - Update loading logic

**Validation:**
- Run existing profile tests to ensure no regression
- Verify 15m crypto agents load with profile only
- Check that risk limits come from profile, not agent grid

### Phase 2: Archive Legacy Agent Specs (HIGH PRIORITY)

**Objective:** Remove duplicate agent specification files

**Steps:**
1. **Archive agent spec files**
   - Move `config/kalshi_btc_15m_agent_spec.py` to `archive/legacy_agent_specs/`
   - Move `config/eth_15m_agent_spec.py` to `archive/legacy_agent_specs/`
   - Move `config/sol_15m_agent_spec.py` to `archive/legacy_agent_specs/`
   - Move `config/xrp_15m_agent_spec.py` to `archive/legacy_agent_specs/`
   - Move `config/doge_15m_agent_spec.py` to `archive/legacy_agent_specs/`

2. **Remove code references**
   - Search for imports of these spec files
   - Remove or update any code that references them
   - Update documentation to reference profile instead

3. **Create README in archive**
   - Document what these files contained
   - Explain why they were archived (duplicate of profile/agent grid)
   - Provide restoration instructions if needed

**Files to Modify:**
- Archive 5 agent spec files
- Search and update any importing code
- Update documentation

**Validation:**
- Search codebase for remaining references to archived files
- Ensure no import errors after removal
- Run tests to verify no breakage

### Phase 3: Clean Up Duplicate Configs (MEDIUM PRIORITY)

**Objective:** Remove unused and duplicate configuration files

**Steps:**
1. **Consolidate agent grid variants**
   - Archive `config/kalshi_agent_grid_clean.yaml` (duplicate of main)
   - Archive `config/kalshi_agent_grid_crypto_backup.yaml` (backup, not needed)
   - Archive `config/kalshi_agent_grid_sports.yaml` (if not used)
   - Keep only `config/kalshi_agent_grid.yaml`

2. **Identify unused YAML configs**
   - Search codebase for references to each YAML config
   - Archive configs with no references
   - Document why each was archived

3. **Consolidate similar configs**
   - Identify configs with overlapping purposes
   - Merge where appropriate
   - Archive duplicates

**Files to Review:**
- `config/kalshi_agent_grid_clean.yaml`
- `config/kalshi_agent_grid_crypto_backup.yaml`
- `config/kalshi_agent_grid_sports.yaml`
- `config/kalshi_expected_spec.yaml`
- `config/kalshi_distance.yaml`
- Other YAML configs with low reference counts

**Validation:**
- Search for references before archiving
- Run tests after each archive
- Verify no missing config errors

### Phase 4: Update Loading Code (HIGH PRIORITY)

**Objective:** Ensure profile takes precedence and conflicts are prevented

**Steps:**
1. **Ensure profile loads before agent grid**
   - Update `config/profiles.py` to load profile early
   - Update `merid/prediction/agent_grid_config.py` to require profile for 15m crypto
   - Add validation that profile is loaded before parsing agent grid

2. **Add conflict detection**
   - Check if agent grid has risk_limits when profile is active
   - Raise error or warning if conflict detected
   - Log which source takes precedence

3. **Add deprecation warnings**
   - Add warning when legacy config paths are used
   - Suggest migration to profile-based config
   - Document deprecation timeline

**Files to Modify:**
- `config/profiles.py` - Profile loader
- `merid/prediction/agent_grid_config.py` - Agent grid config loader
- `config/startup_config_validator.py` - Validation logic

**Validation:**
- Test profile loading with and without agent grid
- Verify conflict detection works
- Check deprecation warnings appear when expected

## Migration Timeline

### Week 1: Phase 1 (Profile Adoption)
- Day 1-2: Move entry window and take profit to profile
- Day 3-4: Remove PROFILE-GATED sections from agent grid
- Day 5: Update loading code and validation
- Testing: Run profile tests, verify 15m crypto agents load

### Week 2: Phase 2 (Archive Agent Specs)
- Day 1-2: Archive agent spec files
- Day 3-4: Remove code references
- Day 5: Create archive README
- Testing: Search for references, run tests

### Week 3: Phase 3 (Clean Up Configs)
- Day 1-2: Consolidate agent grid variants
- Day 3-4: Identify and archive unused configs
- Day 5: Document changes
- Testing: Verify no missing config errors

### Week 4: Phase 4 (Update Loading Code)
- Day 1-2: Update profile loading order
- Day 3-4: Add conflict detection
- Day 5: Add deprecation warnings
- Testing: End-to-end config loading tests

## Rollback Plan

If issues arise during migration:

1. **Restore from git** - Each phase should be committed separately
2. **Re-enable agent grid fallback** - Allow agent grid values if profile not found
3. **Restore archived files** - Move archived files back to config/
4. **Revert loading code changes** - Restore original loading logic

## Success Criteria

- All 15m crypto risk parameters come from profile
- Agent grid contains only agent definitions (no risk limits)
- Legacy agent specs are archived with no code references
- No duplicate or unused configuration files remain
- Profile loading is validated and conflicts are detected
- All tests pass after migration
- Documentation is updated to reflect new structure

## Dependencies

- Profile system must be stable and well-tested
- Existing profile tests must pass
- Code must not have hardcoded references to legacy configs
- Team must agree on canonical configuration decision

## Risks

- **Risk:** Breaking existing agent grid loading
  - **Mitigation:** Comprehensive testing, rollback plan

- **Risk:** Missing config parameters after removal
  - **Mitigation:** Thorough audit of all config references

- **Risk:** Performance impact from profile loading
  - **Mitigation:** Profile loading is already fast, minimal impact expected

- **Risk:** Team unfamiliarity with new structure
  - **Mitigation:** Documentation, training sessions
