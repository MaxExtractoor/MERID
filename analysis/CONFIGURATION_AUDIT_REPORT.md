# Configuration Audit Report

**Date:** 2026-05-13
**Purpose:** Audit configuration sources, identify duplicates, and recommend canonical system

## Executive Summary

The MERID codebase has **51 configuration files** spread across YAML, YML, and Python formats. There are **multiple overlapping configuration systems** that create confusion and potential conflicts. The primary issue is a transition from bankroll-derived risk calculations to profile-based configuration, which has created parallel systems.

## Configuration File Inventory

### YAML Configuration Files (22 files)
- `consensus.yaml` - Consensus algorithm settings
- `crypto_threshold_matrix.yaml` - Edge threshold matrix for crypto trading
- `kalshi_15m_pipelines.yaml` - 15m pipeline configurations
- `kalshi_agent_grid.yaml` - Main agent grid configuration (being migrated)
- `kalshi_agent_grid_clean.yaml` - Clean version of agent grid
- `kalshi_agent_grid_crypto_backup.yaml` - Backup of crypto agent grid
- `kalshi_agent_grid_sports.yaml` - Sports agent grid
- `kalshi_crypto_hedging.yaml` - Crypto hedging configuration
- `kalshi_distance.yaml` - Kalshi distance calculations
- `kalshi_expected_spec.yaml` - Expected Kalshi specifications
- `kalshi_stress_scenarios.yaml` - Stress testing scenarios
- `market_regime.yaml` - Market regime detection
- `models.yaml` - Model configurations
- `pm_profiles.yaml` - Prediction market profiles
- `portfolio_optimizer.yaml` - Portfolio optimization settings
- `profiles/kalshi_crypto_15m.yaml` - **PROFILE-BASED: Single source of truth for 15m crypto**
- `profiles/trade_hold_live.yaml` - Trade hold live profile
- `rate_limits.yaml` - Rate limiting configuration
- `settings.yaml` - General settings
- `ta_engine.yaml` - Technical analysis engine
- `tiered_profit_template.yaml` - Tiered profit taking template
- `trade_hold_config.yaml` - Trade hold configuration

### YML Configuration Files (2 files)
- `agent_manifest.yml` - Agent manifest
- `assertion_templates.yml` - Assertion templates

### Python Configuration Files (27 files)
- `__init__.py` - Config package init
- `agent_modes.py` - Agent mode configurations
- `crypto_alert_config.py` - Crypto alert configuration
- `crypto_spot_kalshi_config.py` - Crypto spot Kalshi configuration
- `crypto_universe.py` - Crypto universe definitions
- `doge_15m_agent_spec.py` - **LEGACY: DOGE 15m agent spec**
- `eth_15m_agent_spec.py` - **LEGACY: ETH 15m agent spec**
- `external_integrations.py` - External integration settings
- `kafka_topics.py` - Kafka topic definitions
- `kalshi_btc_15m_agent_spec.py` - **LEGACY: BTC 15m agent spec**
- `kalshi_crypto_config.py` - **CANONICAL: Crypto asset/frequency constants**
- `kalshi_crypto_series_meta.py` - Crypto series metadata
- `kalshi_ct_risk_profiles.py` - Continuous trader risk profiles
- `kalshi_fee_schedule.py` - Kalshi fee schedule
- `kalshi_sol_15m_agent_spec.py` - **LEGACY: SOL 15m agent spec**
- `kalshi_universe.py` - Kalshi universe definitions
- `kalshi_universe_loader.py` - Kalshi universe loader
- `network.py` - Network configuration
- `ports.py` - Port configuration
- `profiles.py` - Profile loader
- `settings.py` - **DEPRECATED: Use merid.settings instead**
- `sol_15m_agent_spec.py` - **LEGACY: SOL 15m agent spec**
- `spot_basis_config.py` - Spot basis configuration
- `startup_config_validator.py` - Startup configuration validator
- `trading_constants.py` - Trading constants
- `trading_scope.py` - Trading scope definitions
- `xrp_15m_agent_spec.py` - **LEGACY: XRP 15m agent spec**

## Configuration Systems Analysis

### System 1: Profile-Based Configuration (NEW - RECOMMENDED)
**Location:** `config/profiles/kalshi_crypto_15m.yaml`
**Status:** Active, being adopted
**Purpose:** Single source of truth for 15m crypto trading risk parameters

**Key Features:**
- Config-only risk model (no bankroll derivation)
- Explicit capital, venue, asset, and agent caps
- Edge threshold overrides per asset
- Guardrails with absolute USD limits
- Kelly sizing parameters
- Legacy path control (disables balance-derived behavior)

**Activation:** `MERID_PROFILE=kalshi_crypto_15m_v2`

**References:** 12 files reference this profile

### System 2: Agent Grid Configuration (LEGACY - BEING MIGRATED)
**Location:** `config/kalshi_agent_grid.yaml`
**Status:** Active, contains PROFILE-GATED comments
**Purpose:** Define agents, their strategies, and risk limits

**Key Features:**
- Venue and session configuration
- Agent definitions (BTC_15M, ETH_15M, SOL_15M, XRP_15M, DOGE_15M)
- Strategy parameters (edge thresholds, entry windows)
- Risk limits (max positions, orders, notional)
- Take profit configuration

**Migration Status:** 
- Contains `PROFILE-GATED` comments indicating values come from profile
- Line 5: "DEPRECATED for kalshi_crypto_15m_v2 profile"
- Lines 15-16, 34-40: Profile-gated risk limits

**References:** 40+ files reference kalshi_agent_grid

### System 3: Individual Agent Specs (LEGACY - DUPLICATE)
**Locations:** 
- `config/kalshi_btc_15m_agent_spec.py`
- `config/eth_15m_agent_spec.py`
- `config/sol_15m_agent_spec.py`
- `config/xrp_15m_agent_spec.py`
- `config/doge_15m_agent_spec.py`

**Status:** Legacy, duplicates agent grid configuration
**Purpose:** Define agent-specific parameters in Python

**Key Features:**
- Agent identity and description
- Risk parameters (max position size, exposure, stop loss, take profit)
- Entry filters (min edge, vol limits, time to expiry)
- Signal generation logic
- Risk rules integration

**Issue:** These duplicate the configuration already in kalshi_agent_grid.yaml and the profile

### System 4: Crypto Threshold Matrix (ACTIVE - COMPLEMENTARY)
**Location:** `config/crypto_threshold_matrix.yaml`
**Status:** Active, used by profile
**Purpose:** Define edge thresholds per asset/timeframe/archetype

**Key Features:**
- Profile-based edge thresholds
- Confidence bands with Kelly multipliers
- Edge grid by asset and timeframe
- Can be overridden by profile

**Relationship:** Profile references this via `use_crypto_threshold_matrix: true`

### System 5: Kalshi Crypto Config (ACTIVE - CANONICAL CONSTANTS)
**Location:** `config/kalshi_crypto_config.py`
**Status:** Active, canonical source for constants
**Purpose:** Define crypto assets and frequencies

**Key Features:**
- `ACTIVE_CRYPTO_ASSETS`: ["BTC", "ETH", "SOL", "XRP", "DOGE"]
- `ACTIVE_CRYPTO_FREQS`: ["15M"] (15m timeframe only for trading)
- `TOP_N_EDGE_ASSETS`: Environment variable for max assets per cycle
- Asset/timeframe mapping functions

**Issue:** None - this is the canonical source for these constants

## Duplicate Configuration Analysis

### Risk Limits Duplication

**Parameter:** `max_yes_position`, `max_no_position`, `max_notional_usd`

**Sources:**
1. `config/profiles/kalshi_crypto_15m.yaml` (agent_defaults section)
2. `config/kalshi_agent_grid.yaml` (risk_limits section, PROFILE-GATED)
3. Individual agent spec files (risk parameters section)

**Current Behavior:** Profile takes precedence when `MERID_PROFILE=kalshi_crypto_15m_v2`

**Recommendation:** Remove from kalshi_agent_grid.yaml and individual agent specs, keep only in profile

### Edge Thresholds Duplication

**Parameter:** `min_edge_early`, `min_edge_mid`, `min_edge_late`, `min_edge_terminal`

**Sources:**
1. `config/crypto_threshold_matrix.yaml` (edge_grid section)
2. `config/profiles/kalshi_crypto_15m.yaml` (assets section overrides)
3. `config/kalshi_agent_grid.yaml` (strategy section, PROFILE-GATED)
4. Individual agent spec files (entry filters section)

**Current Behavior:** Profile overrides threshold matrix, agent grid has PROFILE-GATED values

**Recommendation:** Keep threshold matrix as baseline, allow profile overrides, remove from agent grid and agent specs

### Entry Window Duplication

**Parameter:** `minutes_before_expiry`, `cutoff_minutes_before_expiry`

**Sources:**
1. `config/profiles/kalshi_crypto_15m.yaml` (agent_defaults section)
2. `config/kalshi_agent_grid.yaml` (entry_window section)
3. Individual agent spec files (entry filters section)

**Current Behavior:** Agent grid values used when profile active (not yet PROFILE-GATED)

**Recommendation:** Move to profile, remove from agent grid and agent specs

## Canonical Configuration Recommendation

### Recommended Architecture

```
config/
├── profiles/
│   ├── kalshi_crypto_15m.yaml          # CANONICAL: Risk limits, caps, edge overrides
│   └── trade_hold_live.yaml            # Trade hold profile
├── crypto_threshold_matrix.yaml        # CANONICAL: Baseline edge thresholds
├── kalshi_crypto_config.py             # CANONICAL: Asset/frequency constants
├── kalshi_agent_grid.yaml             # LEGACY: Agent definitions only (risk limits removed)
└── [other specialized configs]         # Domain-specific (hedging, consensus, etc.)
```

### Migration Plan

#### Phase 1: Complete Profile Adoption
1. Move all risk limits from kalshi_agent_grid.yaml to profile
2. Remove PROFILE-GATED comments from kalshi_agent_grid.yaml
3. Keep only agent definitions (name, assets, timeframes, archetype) in agent grid
4. Update profile activation to be mandatory for 15m crypto

#### Phase 2: Remove Legacy Agent Specs
1. Archive individual agent spec files (btc_15m_agent_spec.py, etc.)
2. Remove any code references to these spec files
3. Update documentation to reference profile instead

#### Phase 3: Clean Up Duplicate Configs
1. Identify and archive unused YAML configs
2. Consolidate similar configs (e.g., multiple agent grid backups)
3. Update imports to use canonical sources

#### Phase 4: Update Loading Code
1. Ensure profile loader is called before agent grid parsing
2. Add validation to prevent profile + agent grid conflicts
3. Add deprecation warnings for legacy config paths

## Priority Actions

### High Priority
1. **Complete profile migration** - Move all risk limits to kalshi_crypto_15m.yaml
2. **Archive legacy agent specs** - Remove btc_15m_agent_spec.py and similar files
3. **Update loading code** - Ensure profile takes precedence

### Medium Priority
1. **Consolidate agent grid variants** - Remove clean/backup/sports variants
2. **Archive unused YAML configs** - Remove configs not referenced in code
3. **Add config validation** - Prevent conflicts between systems

### Low Priority
1. **Standardize config format** - Consider moving all to YAML or all to Python
2. **Add config documentation** - Document each config file's purpose
3. **Config versioning** - Add schema versioning to detect breaking changes

## Conclusion

The codebase has a clear migration path from bankroll-derived risk to profile-based configuration. The profile system (`kalshi_crypto_15m.yaml`) is well-designed and should become the single source of truth for 15m crypto trading configuration. The agent grid should be simplified to define only agent identity and scope, not risk parameters. Legacy agent spec files should be archived as they duplicate configuration already available in the profile and agent grid.
