# Risk Guards and Min/Max Parameters Audit Report

**Date:** 2026-06-28  
**Profile:** kalshi_crypto_15m_v2  
**Scope:** Deep audit of all risk guards and min/max parameters for discrepancies and mismatches

---

## Executive Summary

This audit identified **critical discrepancies** in risk parameter values across multiple risk management components in the MERID codebase. The system has **multiple conflicting sources of truth** for risk limits, with values ranging from 0.5% to 25% for similar parameters across different modules.

### Key Findings

1. **CRITICAL: max_cycle_risk_pct has 5 different values across the codebase**
   - Profile YAML: 0.5% (0.005)
   - Core settings: 3% (0.03)
   - UnifiedRiskManager default: 25% (0.25)
   - Unified enforcement absolute cap: 2% (0.02)
   - Legacy GlobalRiskGuard: 6% (0.06)

2. **CRITICAL: drawdown_halt_pct has 3 different values**
   - Profile YAML: 20% (0.20)
   - Core settings: 10% (0.10)
   - RiskGuard default: 10% (0.10)

3. **CRITICAL: per_trade_risk_pct has conflicting values**
   - Profile YAML: 2% (0.02)
   - Unified enforcement absolute cap: 1% (0.01)
   - UnifiedRiskManager default: 5% (0.05)

4. **DEPRECATED components still present but marked as legacy**
   - GlobalRiskGuard (deprecated in favor of UnifiedRiskManager)
   - GlobalExecutionGuard (deprecated in favor of UnifiedRiskManager)
   - TradingGuard (not used by Kalshi 15m, for legacy paths)

---

## System Architecture Overview

### Production Stack (kalshi_crypto_15m_v2)

The production 15m Kalshi crypto trading system uses the following risk management components:

1. **Primary Risk Envelope:** `merid/risk/profiles/kalshi_crypto_15m_risk_envelope.py`
   - Single canonical function: `compute_kalshi_crypto_15m_risk_envelope()`
   - Loads from: `config/profiles/kalshi_crypto_15m_v2.yaml`
   - Computes all risk parameters from live bankroll and profile config

2. **Profile Adapter:** `merid/risk/profiles/crypto_15m_profile.py`
   - Loads and validates profile YAML
   - Maps YAML to internal risk configuration objects
   - Single integration point for 15m crypto risk configuration

3. **Kalshi-Specific Risk Layer:**
   - `merid/event_venues/kalshi/kalshi_risk.py` (KalshiRiskManager)
   - `merid/event_venues/kalshi/order_gate.py` (PreTradeGate)
   - Profile-driven config from kalshi_crypto_15m_v2.yaml

### Legacy/Deprecated Components

The following components are marked as DEPRECATED but still present in the codebase:

1. **GlobalRiskGuard** (`merid/guards/global_risk_guard.py`)
   - Status: DEPRECATED in favor of UnifiedRiskManager
   - Was previously canonical for Kalshi PM order submissions
   - Default: 6% cycle risk, 6% total risk

2. **GlobalExecutionGuard** (`merid/guards/global_execution_guard.py`)
   - Status: DEPRECATED in favor of UnifiedRiskManager
   - Was designed as "SINGLE chokepoint" for all order execution
   - Default: 3% bankroll cap

3. **TradingGuard** (`trading/guards/trading_guard.py`)
   - Status: NOT used by Kalshi 15m crypto trading
   - Intended for legacy unified trading suite paths (non-Kalshi adapters)
   - Has TradingGuardConfig with no defaults (must be configured)

4. **RiskGuard** (`merid/risk/risk_guard.py`)
   - Status: Core risk guard service, but unclear if used by 15m stack
   - Has RiskLimits with defaults set to 0 (must be configured from live bankroll)
   - Enforces global risk limits, tradable universe, kill switch, dual-approval

5. **UnifiedRiskManager** (`merid/risk/unified_risk_manager.py`)
   - Status: Intended as single source of truth, but has conflicting defaults
   - Loads from config/risk_limits.yaml (if exists)
   - Default: 25% cycle risk, 30% total risk

---

## Risk Parameter Discrepancies

### 1. max_cycle_risk_pct (Maximum risk per cycle)

| Source | Value | Notes |
|--------|-------|-------|
| **Profile YAML** (kalshi_crypto_15m_v2.yaml) | **0.5% (0.005)** | "2026 BEST PRACTICE: 0.5% per cycle for 5-second HFT" |
| **Core Settings** (core/settings.py) | **3% (0.03)** | "2026 best practice" - DEFAULT_CYCLE_RISK_PCT |
| **UnifiedRiskManager** (merid/risk/unified_risk_manager.py) | **25% (0.25)** | Default in RiskLimits dataclass |
| **Unified Enforcement** (merid/config/unified_risk_enforcement.py) | **2% (0.02)** | ABSOLUTE_MAX_CYCLE_RISK_PCT - cannot be exceeded |
| **Legacy GlobalRiskGuard** (merid/guards/global_risk_guard.py) | **6% (0.06)** | Default constructor parameter |
| **Legacy GlobalExecutionGuard** | **3% (0.03)** | Bankroll cap percentage |

**DISCREPANCY:** Values range from 0.5% to 25% (50x difference). This is a **CRITICAL** issue.

**Expected Behavior:** The profile YAML value (0.5%) should be the single source of truth for the 15m Kalshi system.

**Actual Behavior:** Multiple components have different defaults, and it's unclear which one is actually used at runtime.

---

### 2. max_total_risk_pct (Maximum total risk)

| Source | Value | Notes |
|--------|-------|-------|
| **Profile YAML** (kalshi_crypto_15m_v2.yaml) | **15% (0.15)** | "Maximum total risk as percentage of capital (production safety)" |
| **Core Settings** (core/settings.py) | **6% (0.06)** | MAX_TOTAL_RISK_PCT - "2026 best practice" |
| **UnifiedRiskManager** (merid/risk/unified_risk_manager.py) | **30% (0.30)** | Default in RiskLimits dataclass |
| **Legacy GlobalRiskGuard** (merid/guards/global_risk_guard.py) | **6% (0.06)** | Default constructor parameter |

**DISCREPANCY:** Values range from 6% to 30% (5x difference).

---

### 3. drawdown_halt_pct (Drawdown halt percentage)

| Source | Value | Notes |
|--------|-------|-------|
| **Profile YAML** (kalshi_crypto_15m_v2.yaml) | **20% (0.20)** | "RELAXED: Halt at 20% drawdown (increased from 15% to align with industry 25% standard)" |
| **Core Settings** (core/settings.py) | **10% (0.10)** | DRAWDOWN_HALT_PCT - "10% drawdown triggers halt" |
| **RiskGuard** (merid/risk/risk_guard.py) | **10% (0.10)** | Default in RiskLimits dataclass |
| **UnifiedRiskManager** (merid/risk/unified_risk_manager.py) | **10% (0.10)** | Default in RiskLimits dataclass |

**DISCREPANCY:** Profile uses 20%, while core settings and risk guards use 10% (2x difference).

---

### 4. per_trade_risk_pct (Per-trade risk percentage)

| Source | Value | Notes |
|--------|-------|-------|
| **Profile YAML** (kalshi_crypto_15m_v2.yaml) | **2% (0.02)** | "CRITICAL FIX: Aligned to unified risk limit (2% per-trade)" |
| **Unified Enforcement** (merid/config/unified_risk_enforcement.py) | **1% (0.01)** | ABSOLUTE_MAX_RISK_PER_TRADE_PCT - "1% max per individual trade" |
| **UnifiedRiskManager** (merid/risk/unified_risk_manager.py) | **5% (0.05)** | Default in RiskLimits dataclass (per_trade_max_notional_pct) |
| **Kelly Fraction** (profile YAML) | **2% (0.02)** | "CRITICAL FIX: 2% Kelly hard cap (aligned with unified risk limit)" |

**DISCREPANCY:** Values range from 1% to 5% (5x difference). The unified enforcement module caps at 1%, but profile uses 2%.

---

### 5. max_daily_loss_pct (Daily loss cap)

| Source | Value | Notes |
|--------|-------|-------|
| **Profile YAML** (kalshi_crypto_15m_v2.yaml) | **5% (0.05)** | "2026 best practice: 5% for both test and prod" |
| **Core Settings** (core/settings.py) | **5% (0.05)** | DAILY_LOSS_CAP_PCT - "5% default (2026 best practice)" |
| **UnifiedRiskManager** (merid/risk/unified_risk_manager.py) | **3% (0.03)** | Default in RiskLimits dataclass (daily_loss_pct) |

**DISCREPANCY:** Profile and core settings agree at 5%, but UnifiedRiskManager default is 3%.

---

### 6. min_confidence_for_trade (Minimum confidence threshold)

| Source | Value | Notes |
|--------|-------|-------|
| **Profile YAML** (kalshi_crypto_15m_v2.yaml) | **65% (0.65)** | "INCREASED from 0.50 to 0.65 based on GRDazzle research" |
| **RiskGuard** (merid/risk/risk_guard.py) | **50% (0.50)** | Default in RiskLimits dataclass |
| **Snapshots** (legacy) | **70% (0.70)** | Old snapshot values |

**DISCREPANCY:** Profile uses 65%, RiskGuard default is 50%.

---

### 7. max_spread_cents (Maximum spread in cents)

| Source | Value | Notes |
|--------|-------|-------|
| **Profile YAML** (kalshi_crypto_15m_v2.yaml) | **50 cents** | "INCREASED: 50c to accommodate realistic 15m market spreads" |
| **Profile YAML (guardrails)** | **50 cents** | guardrails.max_spread_cents |
| **Profile YAML (universe)** | **10 cents** | universe.max_spread_cents - "REVERTED from 100c" |
| **Profile YAML (momentum_fvg)** | **50 cents** | momentum_fvg.spread_gate_cents |
| **Legacy snapshots** | **30-70 cents** | Various old values |

**DISCREPANCY:** Multiple spread limits in the same profile (10c, 50c). The universe filter uses 10c while guardrails use 50c.

---

### 8. min_depth_thresholds (Minimum order book depth)

| Source | Value | Notes |
|--------|-------|-------|
| **Profile YAML (per-asset)** | **1 contract** | min_depth_yes: 1, min_depth_no: 1 for all assets |
| **Profile YAML (guardrails)** | **2 contracts** | guardrails.min_depth_contracts: 2 |
| **Profile YAML (guardrails tiered)** | **Tier 1: 2, Tier 2: 1** | min_depth_yes_tier1: 2, min_depth_yes_tier2: 1 |
| **TRADING_CONDITIONS_AUDIT.md** | **5-10 contracts** | References to 5-10 contract thresholds |

**DISCREPANCY:** Multiple depth thresholds in the same profile (1, 2, 5-10 contracts).

---

### 9. max_single_order_contracts (Maximum contracts per order)

| Source | Value | Notes |
|--------|-------|-------|
| **Profile YAML (per-asset)** | **2 contracts** | max_contracts: 2 for BTC, ETH, SOL, XRP, DOGE |
| **Profile YAML (contract_caps)** | **10 contracts** | contract_caps.max_single_order_contracts: 10 |
| **Profile YAML (failsafe)** | **1 contract** | failsafe.max_contracts_per_order: 1 |
| **TradingGuard** | **10 contracts** | Default in TradingGuardConfig |

**DISCREPANCY:** Multiple contract limits in the same profile (1, 2, 10 contracts).

---

### 10. rate limiting parameters

| Parameter | Profile YAML | RiskGuard | UnifiedRiskManager | Notes |
|-----------|--------------|----------|-------------------|-------|
| max_trades_per_hour | N/A (uses throttling) | 20 | 20 | Agreement |
| min_time_between_trades | 15s (per_asset_cooldown) | 60s | 60s | Profile uses 15s, others use 60s |
| global_orders_limit | 15/min | N/A | N/A | Profile-specific |
| max_orders_per_15m_window | 15 | N/A | N/A | Profile-specific |

**DISCREPANCY:** Profile uses 15s cooldown, RiskGuard/UnifiedRiskManager use 60s.

---

## Configuration Hierarchy and Precedence

### Documented Hierarchy (from profile YAML comments)

The profile YAML claims to be the "SINGLE SOURCE OF TRUTH" and states:

```
When MERID_PROFILE=kalshi_crypto_15m_v2 is active, this profile overrides
all other risk configuration sources:
  - kalshi_agent_grid.yaml risk_limits (set to 0 = profile-gated)
  - kalshi_15m_crypto_config.py GLOBAL_RISK_LIMITS (profile takes precedence)
  - KalshiRiskConfig defaults (profile values applied at initialization)
  - capabilities.py max_concurrent_trades (profile value used)
```

### Actual Hierarchy (based on code analysis)

The actual hierarchy is unclear due to:

1. **Multiple entry points:** Different components load from different sources
2. **Environment variable overrides:** core.settings.py reads from environment variables
3. **Deprecated components still present:** Legacy guards may still be imported
4. **No central enforcement:** unified_risk_enforcement.py exists but may not be called

### Potential Code Paths

1. **Production 15m path:** Profile YAML → Crypto15mProfileAdapter → KalshiRiskConfig
2. **Legacy path:** core.settings.py → GlobalRiskGuard/GlobalExecutionGuard
3. **Unified path:** config/risk_limits.yaml → UnifiedRiskManager
4. **TradingGuard path:** TradingGuardConfig (from profile or env vars)

---

## Determinism Gaps

### 1. Non-Deterministic Configuration Loading

**Issue:** Risk parameters are loaded from multiple sources with unclear precedence.

**Examples:**
- `MAX_CYCLE_RISK_PCT` can come from: environment variable, core.settings.py default, profile YAML, or UnifiedRiskManager default
- The actual value used depends on which component is instantiated first and which import path is taken

**Impact:** System behavior is non-deterministic; different runs may use different risk limits.

---

### 2. Bankroll-Tiered Dynamic Sizing

**Issue:** Profile YAML specifies bankroll-tiered per-trade risk:

```yaml
per_trade_risk_pct:
  value: 0.02  # Default 2%
  dynamic: bankroll_tiered  # Computed from live bankroll via RiskEnvelopeService
  bankroll_tier_small_usd: 100.0
  bankroll_tier_medium_usd: 1000.0
  per_trade_risk_small_pct: 0.03  # 3% for bankroll < $100
  per_trade_risk_medium_pct: 0.02  # 2% for bankroll $100-$1k
  per_trade_risk_large_pct: 0.02  # 2% for bankroll > $1k
```

**Impact:** Risk limits change dynamically based on live bankroll, making behavior non-deterministic across different account states.

---

### 3. Adaptive Risk Bands

**Issue:** Profile YAML specifies adaptive risk scaling based on drawdown:

```yaml
adaptive_risk_bands:
  - max_drawdown_pct: 0.10  # 10% - normal risk (100% multiplier)
    multiplier: 1.0
  - max_drawdown_pct: 0.12  # 12% - reduced risk (50% multiplier)
    multiplier: 0.5
  - max_drawdown_pct: 0.15  # 15% - critical risk (25% multiplier)
    multiplier: 0.25
  - max_drawdown_pct: 1.00  # halt (0% multiplier)
    multiplier: 0.0
```

**Impact:** Risk limits change dynamically based on drawdown state, making behavior non-deterministic across different performance states.

---

### 4. Operation Mode Switching

**Issue:** Profile YAML has operation_mode (test vs prod) that affects daily loss limits:

```yaml
operation_mode: prod  # Options: test, prod
max_daily_loss_pct:
  test: 0.05  # 5% daily loss limit for test mode
  prod: 0.05  # 5% daily loss limit for prod mode
```

**Impact:** Risk limits change based on operation mode, making behavior non-deterministic across different deployments.

---

### 5. Multiple Risk Envelopes

**Issue:** The system has multiple risk envelope implementations:
- `KalshiCrypto15mRiskEnvelope` (profile-specific)
- `RiskLimits` (RiskGuard)
- `RiskLimits` (UnifiedRiskManager)
- `TradingGuardConfig` (TradingGuard)

**Impact:** Which envelope is used depends on the code path, leading to non-deterministic behavior.

---

### 6. Environment Variable Overrides

**Issue:** core.settings.py allows environment variable overrides for all risk parameters:

```python
MAX_CYCLE_RISK_PCT: float = float(os.getenv("MAX_CYCLE_RISK_PCT", _DEFAULT_CYCLE_RISK_PCT))
MAX_TOTAL_RISK_PCT: float = float(os.getenv("MAX_TOTAL_RISK_PCT", "0.06"))
DAILY_LOSS_CAP_PCT: float = float(os.getenv("DAILY_LOSS_CAP_PCT", "0.05"))
```

**Impact:** Risk limits can be changed at deployment time without code changes, making behavior non-deterministic across different environments.

---

## Current System Setup Documentation

### Active Profile: kalshi_crypto_15m_v2

**Profile Version:** 2.2.0  
**Description:** "Config-only risk model for 15m crypto prediction markets on Kalshi with profitability enhancements"

### Assets Covered

- BTC/USD
- ETH/USD
- SOL/USD
- XRP/USD
- DOGE/USD

### Key Risk Parameters (from Profile YAML)

| Parameter | Value | Description |
|-----------|-------|-------------|
| capital_usd | 0 | Derive from live Kalshi bankroll API |
| min_notional_usd | 0.50 | Minimum notional per trade |
| max_cycle_risk_pct | 0.005 (0.5%) | Maximum risk per cycle |
| max_total_risk_pct | 0.15 (15%) | Maximum total risk cap |
| per_trade_risk_pct | 0.02 (2%) | Per-trade risk (bankroll-tiered) |
| drawdown_halt_pct | 0.20 (20%) | Drawdown halt percentage |
| max_daily_loss_pct | 0.05 (5%) | Daily loss cap (test and prod) |
| kelly_fraction | 0.02 (2%) | Kelly hard cap |
| max_spread_cents | 50 | Maximum spread in cents |
| min_confidence_threshold | 0.65 (65%) | Minimum confidence to execute |

### Per-Asset Configuration

All assets (BTC, ETH, SOL, XRP, DOGE) have:
- max_notional_pct: 5% (0.05)
- max_contracts: 2
- min_depth_yes: 1
- min_depth_no: 1

### Throttling Configuration

| Parameter | Value |
|-----------|-------|
| global_orders_limit | 15 per minute |
| per_asset_cooldown_sec | 15 seconds |
| max_orders_per_15m_window | 15 |

### Guardrails Configuration

| Parameter | Value |
|-----------|-------|
| max_spread_cents | 50 |
| max_slippage_cents | 5 |
| min_depth_contracts | 2 |
| min_post_fee_edge | 0.015 (1.5%) |
| min_time_to_expiry_min | 2.0 |
| min_contract_price_cents | 50 |
| max_contract_price_cents | 70 |

### Signal Mode

- **Current:** momentum_fvg
- **Options:** mean_reversion, momentum_fvg, hybrid, price_based

### Profitability Enhancements (Phase 1)

- yes_no_arbitrage: enabled (threshold_cents: 3, max_size_contracts: 10)
- market_making: enabled (quoting_mode: two_sided, spread_cents: 2)
- correlation_tracking: enabled (threshold: 0.5, max_reduction: 0.4)

### Position Management

- offset_hedging: enabled (hedge_ratio: 0.30)
- trailing_stop: enabled (trailing_distance_cents: 5, min_profit_cents: 12)
- staged_time_exit: enabled (stages at 5, 10, 13 minutes)
- dynamic_sizing: enabled (base_contracts: 1, max_contracts: 3)

---

## Recommendations

### Critical Priority (P0)

1. **Establish single source of truth for max_cycle_risk_pct**
   - Decide whether profile YAML (0.5%) or core.settings (3%) is the canonical value
   - Remove or align all other sources to this value
   - Add validation to detect mismatches at startup

2. **Resolve drawdown_halt_pct discrepancy**
   - Profile uses 20%, core.settings uses 10%
   - Decide which value is correct and align all sources

3. **Resolve per_trade_risk_pct discrepancy**
   - Profile uses 2%, unified enforcement caps at 1%
   - These values are incompatible and will cause rejections

4. **Remove or deprecate unused risk guard components**
   - GlobalRiskGuard is deprecated but still present
   - GlobalExecutionGuard is deprecated but still present
   - RiskGuard may not be used by 15m stack
   - Either remove these or clearly document their status

### High Priority (P1)

5. **Unify spread limits within profile YAML**
   - Currently has 10c (universe), 50c (guardrails), 50c (momentum_fvg)
   - Decide on single value and use consistently

6. **Unify depth thresholds within profile YAML**
   - Currently has 1 (per-asset), 2 (guardrails), 1-2 (tiered)
   - Decide on single value and use consistently

7. **Unify contract limits within profile YAML**
   - Currently has 2 (per-asset), 10 (contract_caps), 1 (failsafe)
   - Decide on single value and use consistently

8. **Align rate limiting parameters**
   - Profile uses 15s cooldown, RiskGuard uses 60s
   - Decide which is correct and align all sources

### Medium Priority (P2)

9. **Document actual configuration hierarchy**
   - Current documentation claims profile is single source of truth
   - Actual code has multiple paths with unclear precedence
   - Create clear documentation of which component loads which parameters

10. **Add startup validation**
    - Call unified_risk_enforcement.enforce_at_startup() in main_15m_lean.py
    - Detect and report parameter mismatches at startup
    - Fail fast if critical discrepancies are detected

11. **Remove environment variable overrides for critical risk parameters**
    - Or clearly document which parameters can be overridden
    - Add validation to prevent unsafe overrides

12. **Improve determinism**
    - Consider removing bankroll-tiered dynamic sizing
    - Consider removing adaptive risk bands
    - Or clearly document these as intentional non-deterministic features

---

## Appendix: File Inventory

### Risk Guard Components

| File | Status | Purpose |
|------|--------|---------|
| merid/risk/risk_guard.py | Active? | Core RiskGuard service with RiskLimits |
| merid/risk/profiles/kalshi_crypto_15m_risk_envelope.py | **Production** | Single canonical function for 15m risk parameters |
| merid/risk/profiles/crypto_15m_profile.py | **Production** | Profile adapter for loading YAML config |
| merid/risk/unified_risk_manager.py | Intended? | Unified risk manager (conflicting defaults) |
| merid/guards/global_risk_guard.py | **DEPRECATED** | Legacy global risk guard |
| merid/guards/global_execution_guard.py | **DEPRECATED** | Legacy global execution guard |
| trading/guards/trading_guard.py | Legacy | Not used by Kalshi 15m |
| merid/config/unified_risk_enforcement.py | Enforcement | Validates configs against absolute invariants |

### Configuration Files

| File | Purpose |
|------|---------|
| config/profiles/kalshi_crypto_15m_v2.yaml | **Production profile** - single source of truth for 15m |
| core/settings.py | Global settings with environment variable overrides |
| config/risk_limits.yaml | UnifiedRiskManager config (may not exist) |
| config/portfolio_optimizer.yaml | Portfolio optimizer config (legacy?) |
| config/trade_hold_config.yaml | Trade hold config (legacy?) |

### Test Files

| File | Purpose |
|------|---------|
| tests/test_risk_guard.py | Tests for RiskGuard |
| tests/test_crypto_15m_profile_fixes.py | Tests for profile adapter |
| tests/test_kalshi_crypto_15m_risk_envelope.py | Tests for risk envelope |
| tests/risk/test_unified_risk_enforcement.py | Tests for unified enforcement |
| tests/trading/test_risk_oversizing_regression.py | Tests for risk oversizing bug |

---

## Conclusion

The MERID codebase has a **critical risk configuration discrepancy problem**. Multiple risk guard components exist with conflicting parameter values, and it's unclear which values are actually used at runtime. The profile YAML claims to be the "single source of truth" but other components (core.settings, UnifiedRiskManager, deprecated guards) have different defaults.

**Immediate action required:**
1. Establish which component is the actual source of truth for the 15m Kalshi system
2. Align all other components to this source
3. Add startup validation to detect mismatches
4. Remove or clearly deprecate unused components

**Risk assessment:** HIGH - The current state could lead to:
- Unexpected risk exposure if wrong limits are used
- System rejections if limits are too tight
- Oversizing if limits are too loose
- Non-deterministic behavior across different deployments
